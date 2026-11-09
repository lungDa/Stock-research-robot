"""Probe an optional report source. Never changes financial values or rankings.
Two requests maximum; metadata and one report only; 512 KiB / 6s each.
"""
import json,os,re,time
from datetime import date
from app.providers.bounded_http import fetch_json

BASE='https://api.datasink.ing'
SAFE_FIELDS=('id','symbol','exchange','stock_code','stock_name','report_period','doc_type','title')


def probe(symbol,key,fetch=fetch_json):
    if not re.fullmatch(r'\d{4}\.TW',symbol):raise ValueError('Probe requires a four-digit TWSE ticker, e.g. 2330.TW')
    # Query authentication is the REST format documented by the provider. Never
    # print exception messages, request URLs, headers, or the response body.
    meta=fetch(BASE+'/documents',{'symbol':symbol,'order':'desc','size':1,'page':1,'apikey':key},
               max_bytes=65536,seconds=6)
    if not isinstance(meta,dict) or not isinstance(meta.get('items'),list) or not meta['items']:
        raise ValueError('No matching report metadata')
    item=meta['items'][0]
    if not isinstance(item,dict) or item.get('symbol')!=symbol or item.get('exchange')!='twse':
        raise ValueError('Report identity mismatch')
    if str(item.get('stock_code'))!=symbol.split('.')[0]:raise ValueError('Company code mismatch')
    ident=item.get('id')
    if type(ident) is not int or ident<=0:raise ValueError('Invalid report id')
    period=date.fromisoformat(str(item.get('report_period','')))
    if period>date.today():raise ValueError('Future reporting period')
    doc=fetch(BASE+'/documents/'+str(ident),{'apikey':key},max_bytes=524288,seconds=6)
    if not isinstance(doc,dict) or doc.get('symbol')!=symbol or doc.get('id')!=ident or doc.get('report_period')!=str(period):
        raise ValueError('Full report identity or period mismatch')
    content=doc.get('content')
    if not isinstance(content,str) or not content.strip():raise ValueError('Empty report text')
    # Presence is diagnostic only. A keyword does not prove period/unit/value.
    markers={name:any(s in content for s in needles) for name,needles in {
        'eps_labels':('基本每股盈餘','基本每股盈余','每股盈餘','每股盈余'),
        'income_labels':('本期淨利','本期净利'),
        'equity_labels':('權益總額','权益总额','權益總計'),
        'paid_dividend_labels':('支付之股利','發放股利','發放現金股利')}.items()}
    return {'report':{k:item.get(k) for k in SAFE_FIELDS},'content_bytes':len(content.encode('utf-8')),
            'markers':markers,'numeric_values_verified':False,
            'status':'report_access_verified; numeric_extraction_not_enabled'}


def main():
    key=os.getenv('DATASINK_API_KEY','').strip()
    if not key:raise SystemExit('Set GitHub Secret DATASINK_API_KEY; no request was sent.')
    symbol=os.getenv('REPORT_PROBE_SYMBOL','2330.TW').strip().upper()
    try:result=probe(symbol,key)
    except Exception as exc:
        # A fixed error category prevents accidental key exposure via HTTP URLs.
        print('Report backup validation failed ('+type(exc).__name__+'). No financial data was changed.')
        raise SystemExit(1)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
