from datetime import date
from unittest.mock import Mock
import pytest
from app.db import get,put
from app.providers.twse_eps import parse_texts,parse_pdf
from app.services.multifactor import annual_rows

TODAY=date(2026,11,9)
IDENTITY='公司名稱 中華電信股份有限公司\n產製日期: 2026/11/09\n股票代號:2412'
# Numeric rows transcribed from the official TWSE company profile, accessed 2026-11-09.
# https://www.twse.com.tw/pdf/ch/2412_ch.pdf ; pretax profit is NOT EPS.
TABLE='''年度 第一季 半年度 前三季 全年度 每股盈餘 繼續營業單位稅前淨利(千元)
2021年 1.14 11,320,348 2.29 22,785,290 3.50 34,886,808 4.61 46,066,624
2022年 1.17 11,674,393 2.41 24,177,291 3.62 36,383,546 4.70 47,228,950
2023年 1.24 12,259,993 2.52 24,919,653 3.69 36,557,134 4.76 46,992,646
2024年 1.21 11,987,740 2.48 24,334,465 3.64 35,823,567 4.80 47,753,789
2025年 1.26 12,699,011 2.57 25,829,268 3.79 38,087,342 4.99 50,269,600
2026年 1.30 13,180,725 2.68 27,133,507 - - - -
'''


def test_annual_eps_uses_seventh_cell_not_pretax_profit_or_ytd():
    result=parse_texts([IDENTITY,TABLE],'2412.TW',TODAY)
    assert result['rows']['2025']['eps']==4.99 and result['rows']['2021']['eps']==4.61
    assert len(result['rows'])==5 and '2026' not in result['rows']
    assert result['rows']['2025']['period_end']=='2025-12-31'


@pytest.mark.parametrize('identity,table,symbol',[
    (IDENTITY.replace('2412','2330'),TABLE,'2412.TW'),
    (IDENTITY.replace('2026/11/09','2025/11/09'),TABLE,'2412.TW'),
    (IDENTITY.replace('2026/11/09','2027/11/09'),TABLE,'2412.TW'),
    (IDENTITY,TABLE.replace('全年度','不明期間'),'2412.TW'),
    (IDENTITY,TABLE,'2412.TWO'),
])
def test_identity_period_and_market_guard(identity,table,symbol):
    with pytest.raises(ValueError):parse_texts([identity,table],symbol,TODAY)


def test_conflicting_rows_rejected_and_unknown_columns_not_guessed():
    with pytest.raises(ValueError):parse_texts([IDENTITY,TABLE,TABLE.replace('4.99','9.99')],'2412.TW',TODAY)
    with pytest.raises(ValueError):parse_texts([IDENTITY,TABLE.replace('202','invalid202')],'2412.TW',TODAY)


def test_non_pdf_rejected():
    with pytest.raises(ValueError):parse_pdf(b'<html>blocked</html>','2412.TW',TODAY)


def test_binary_pdf_to_verified_rows():
    """Exercise real pypdf layout extraction with an in-memory Unicode PDF."""
    import io,hashlib
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,NumberObject,ArrayObject,DecodedStreamObject,TextStringObject
    text=IDENTITY+'\n'+TABLE
    chars=sorted(set(text)-{'\n'});codes={c:i+1 for i,c in enumerate(chars)}
    cmap=DecodedStreamObject()
    mapping='\n'.join(f'<{code:04X}> <{c.encode("utf-16-be").hex()}>' for c,code in codes.items())
    cmap.set_data(('begincmap\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n'+str(len(chars))+' beginbfchar\n'+mapping+'\nendbfchar\nendcmap').encode())
    writer=PdfWriter();page=writer.add_blank_page(width=800,height=1000)
    descendant=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/CIDFontType0'),
        NameObject('/BaseFont'):NameObject('/STSong-Light'),NameObject('/DW'):NumberObject(500),
        NameObject('/CIDSystemInfo'):DictionaryObject({NameObject('/Registry'):TextStringObject('Adobe'),NameObject('/Ordering'):TextStringObject('GB1'),NameObject('/Supplement'):NumberObject(0)})})
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type0'),
        NameObject('/BaseFont'):NameObject('/STSong-Light'),NameObject('/Encoding'):NameObject('/Identity-H'),
        NameObject('/DescendantFonts'):ArrayObject([writer._add_object(descendant)]),NameObject('/ToUnicode'):writer._add_object(cmap)})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject()
    lines=[''.join(f'{codes[c]:04X}' for c in line) for line in text.splitlines()]
    stream.set_data(('BT /F1 8 Tf 12 TL 10 950 Td '+' T* '.join('<'+line+'> Tj' for line in lines)+' ET').encode())
    page[NameObject('/Contents')]=writer._add_object(stream)
    output=io.BytesIO();writer.write(output);raw=output.getvalue()
    result=parse_pdf(raw,'2412.TW',TODAY)
    assert result['rows']['2025']['eps']==4.99 and len(result['rows'])==5
    assert result['sha256']==hashlib.sha256(raw).hexdigest()


def test_worker_merges_history_and_preserves_private_data(monkeypatch):
    import jobs.refresh_eps as job
    monkeypatch.setattr(job,'fetch',lambda *a:parse_texts([IDENTITY,TABLE],'2412.TW',TODAY))
    put('eps:official:2412.TW',{'rows':{'2020':{'eps':4.31}}})
    put('annual:Ualice:2412.TW',{'2025':{'eps':5.1,'provenance':'user_import'}})
    result=job.run(['2412'])
    assert result['eps_requests']==1
    assert len(get('eps:official:2412.TW')['rows'])==6
    assert annual_rows('Ualice','2412.TW')['2025']['eps']==5.1
    assert annual_rows('Ubob','2412.TW')['2025']['eps']==4.99


def test_worker_failure_keeps_previous_values_and_respects_retry(monkeypatch):
    import jobs.refresh_eps as job
    put('eps:official:2412.TW',{'rows':{'2025':{'eps':4.99}}})
    loader=Mock(side_effect=ValueError('changed table'));monkeypatch.setattr(job,'fetch',loader)
    assert job.run(['2412'])['state']=='failed'
    job.run(['2412'])
    assert loader.call_count==1 and get('eps:official:2412.TW')['rows']['2025']['eps']==4.99
