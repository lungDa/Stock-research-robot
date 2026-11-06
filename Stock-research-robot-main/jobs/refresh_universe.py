"""從證交所 ISIN 與 Nasdaq Trader 更新上市/上櫃股票、ETF 母體。"""
from io import StringIO
from pathlib import Path
import csv,re,requests,pandas as pd

def build():
    rows=[]
    for mode,suffix in [('2','.TW'),('4','.TWO')]:
        before=len(rows)
        response=requests.get('https://isin.twse.com.tw/isin/C_public.jsp',params={'strMode':mode},timeout=30)
        response.raise_for_status(); response.encoding='big5'
        tables=pd.read_html(StringIO(response.text),header=0)
        for _,r in tables[0].iterrows():
            cells=[str(x).strip() for x in r.values]
            # ISIN 表第六欄為 CFI code；股票 ES、ETF CE。
            if len(cells)<6 or not cells[5].startswith(('ES','CE')): continue
            match=re.match(r'^(\d{4,6})[\s\u3000]+(.+)$',cells[0])
            if match: rows.append({'symbol':match[1]+suffix,'name':match[2]})
        if len(rows)==before: raise RuntimeError(f'台股來源{mode}解析為空，保留舊母體')
    for filename,symbol_column,name_column in [('nasdaqlisted.txt','Symbol','Security Name'),('otherlisted.txt','ACT Symbol','Security Name')]:
        before=len(rows)
        r=requests.get('https://www.nasdaqtrader.com/dynamic/SymDir/'+filename,timeout=30);r.raise_for_status()
        for item in csv.DictReader(StringIO(r.text),delimiter='|'):
            symbol=item.get(symbol_column,'')
            name=item.get(name_column,'')
            if item.get('Test Issue')!='N' or not symbol: continue
            # 排除可辨識的權證、單位與特別股；最終商品分類仍由行情資料確認。
            if any(x in name.lower() for x in ['warrant',' unit','preferred','depositary shares']): continue
            if not re.fullmatch(r'[A-Z]+(?:[.$][A-Z])?',symbol): continue
            rows.append({'symbol':symbol.replace('.','-').replace('$','-'),'name':name})
        if len(rows)==before: raise RuntimeError(f'{filename}解析為空，保留舊母體')
    if not rows: raise RuntimeError('取得空母體，保留舊檔')
    out=Path('data/universe.csv'); temp=out.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['symbol','name']);writer.writeheader()
        writer.writerows({r['symbol']:r for r in rows}.values())
    temp.replace(out)
    print(f'母體已更新：{len(rows)} 筆（可能含重複；寫入時已去重）')
if __name__=='__main__': build()
