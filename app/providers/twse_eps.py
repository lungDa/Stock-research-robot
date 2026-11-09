"""Full-year EPS from TWSE company profiles, never the adjacent pretax profit.

Contract: fixed TWSE HTTPS host, 4-digit listed company, bounded PDF, matching
identity and report date, eight numeric cells per annual row. Reject ambiguity.
"""
import io,re,time,hashlib,unicodedata
from datetime import date
import requests
from pypdf import PdfReader
from app.providers.annual_free import finite

BASE='https://www.twse.com.tw/pdf/ch/'


def parse_texts(texts,symbol,today):
    texts=[unicodedata.normalize('NFKC',text) for text in texts]
    code=symbol.split('.')[0]
    if not re.fullmatch(r'\d{4}\.TW',symbol):raise ValueError('TWSE listed stocks only')
    all_text='\n'.join(texts)
    identities=set(re.findall(r'股票代號\s*[:：]\s*(\d{4})(?!\d)',all_text))
    if identities!={code}:raise ValueError('Company identity mismatch')
    stamps=re.findall(r'產製日期\s*[:：]\s*(\d{4}/\d{1,2}/\d{1,2})',all_text)
    if len(set(stamps))!=1:raise ValueError('Missing report date')
    stamp=date(*map(int,stamps[0].split('/')))
    if not 0<=(today-stamp).days<=45:raise ValueError('Stale or future report')
    rows={};url=BASE+code+'_ch.pdf'
    token=r'(?:-?\d[\d,]*(?:\.\d+)?|-)'
    pattern=re.compile(r'^\s*(20\d{2})年\s+('+r'\s+'.join([token]*8)+r')\s*$')
    for page in texts:
        compact=re.sub(r'\s+','',page)
        if not all(s in compact for s in ('第一季','半年度','前三季','全年度','每股盈餘','淨利(千元)')):continue
        for line in page.splitlines():
            match=pattern.fullmatch(line)
            if not match:continue
            year=int(match[1]);cells=match[2].split()
            if not today.year-11<=year<today.year or cells[6]=='-':continue
            value=finite(cells[6].replace(',',''))
            if value is None:continue
            key=str(year)
            if key in rows and rows[key]['eps']!=value:raise ValueError('Conflicting annual EPS')
            rows[key]={'eps':value,'currency':'TWD','period_start':f'{year}-01-01',
                'period_end':f'{year}-12-31','source_url':url,'provenance':'TWSE_company_profile',
                'as_of':str(stamp),'eps_basis':'reported_full_year_EPS; not quarterly sum',
                'field_sources':{'eps':{'url':url,'provenance':'TWSE_company_profile','as_of':str(stamp),
                    'unit':'TWD_PER_SHARE','basis':'reported_full_year_EPS'}}}
    if not rows:raise ValueError('No unambiguous full-year EPS table')
    valuation={}
    for page in texts:
        if '本益比' not in page:continue
        active=False
        for line in page.splitlines():
            if re.fullmatch(r'\s*(?:日期\s+本益比\s*)+',line):
                active=True;continue
            if not active:continue
            pair=r'\d{1,2}/\d{1,2}\s+-?\d+(?:\.\d+)?'
            if not re.fullmatch(r'\s*'+pair+r'(?:\s+'+pair+r')*\s*',line):
                if line.strip():active=False
                continue
            for month,day,value in re.findall(r'(\d{1,2})/(\d{1,2})\s+(-?\d+(?:\.\d+)?)',line):
                try:
                    year=stamp.year if (int(month),int(day))<=(stamp.month,stamp.day) else stamp.year-1
                    quote_day=date(year,int(month),int(day));pe=finite(value)
                except ValueError:continue
                if pe is not None and pe>0 and 0<=(today-quote_day).days<=14:
                    if str(quote_day) in valuation and valuation[str(quote_day)]!=pe:raise ValueError('Conflicting profile PE')
                    valuation[str(quote_day)]=pe
    result={'rows':rows,'report_date':str(stamp),'source':url}
    if valuation:
        day=max(valuation)
        result['valuation']={'pe':{'value':valuation[day],'as_of':day,'source':url,
            'basis':'TWSE company profile reported PE; not inferred EPS','provenance':'TWSE_company_profile'}}
    return result


def parse_pdf(raw,symbol,today):
    if not raw.startswith(b'%PDF-') or len(raw)>4*1024*1024:raise ValueError('Invalid PDF')
    reader=PdfReader(io.BytesIO(raw),strict=True)
    if reader.is_encrypted or not 1<=len(reader.pages)<=8:raise ValueError('Unexpected profile PDF')
    texts=[page.extract_text(extraction_mode='layout') or '' for page in reader.pages]
    result=parse_texts(texts,symbol,today)
    result['sha256']=hashlib.sha256(raw).hexdigest()
    return result


def fetch(symbol,today):
    if not re.fullmatch(r'\d{4}\.TW',symbol):raise ValueError('TWSE listed stocks only')
    url=BASE+symbol.split('.')[0]+'_ch.pdf';start=time.monotonic();chunks=[];size=0
    with requests.get(url,timeout=(2,2),stream=True,allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code!=200:raise ValueError('No direct PDF')
        for chunk in response.iter_content(8192):
            size+=len(chunk)
            if size>4*1024*1024 or time.monotonic()-start>6:raise ValueError('PDF exceeds budget')
            chunks.append(chunk)
    return parse_pdf(b''.join(chunks),symbol,today)
