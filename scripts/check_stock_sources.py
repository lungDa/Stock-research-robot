"""One manual source diagnostic, at most six requests; no DB writes or messages."""
import argparse,json,os
from datetime import timedelta
from app.providers.market import normalize
from app.providers.mopsfin import request,parse_catalog,parse_company,parse_annual,annual_fields,company_code
from app.providers.twse_eps import fetch as pdf_fetch
from app.providers.bounded_http import fetch_json
from app.providers.annual_free import FINMIND
from app.providers.finmind_batch import SourceRejected
from app.providers.tw_daily import parse as price_parse
from app.providers.source_errors import describe
from app.services.freshness import local_now
import time


def diagnose(symbol,official=request,pdf=pdf_fetch,prices=fetch_json,token=''):
    symbol=normalize(symbol);company_code(symbol);today=local_now().date();count=0;results={};stage='官方目錄下載'
    try:
        count+=1;body=official('/');stage='官方目錄解析';catalog=parse_catalog(body)
        stage='公司查詢下載';count+=1;body=official('/suggestCompany',params={'query':company_code(symbol)})
        stage='公司查詢解析';display=parse_company(body,symbol)
        for field in ('eps','roe_pct'):
            stage='年度'+field+'下載';count+=1
            body=official('/compare/data',form=annual_fields(field,display,catalog[field]))
            stage='年度'+field+'解析';rows=parse_annual(body,symbol,field,display,today,catalog[field])
            results['mopsfin_'+field]={'status':'ok','years':sorted(rows)}
    except Exception as exc:results['mopsfin_failure']={'status':'failed',**describe(exc,stage)}
    if symbol.endswith('.TW'):
        count+=1
        try:
            result=pdf(symbol,today)
            results['annual_eps_pdf']={'status':'ok','years':sorted(result['rows']),'report_date':result['report_date'],
                'pe_available':bool(result.get('valuation',{}).get('pe'))}
        except Exception as exc:results['annual_eps_pdf']={'status':'failed',**describe(exc,'TWSE年度EPS PDF')}
    if token:
        count+=1
        try:
            body=prices(FINMIND,{'dataset':'TaiwanStockPrice','data_id':company_code(symbol),
                'start_date':str(today-timedelta(days=160)),'end_date':str(today)},
                headers={'Authorization':'Bearer '+token},max_bytes=262144,seconds=6)
            if not isinstance(body,dict) or body.get('status')!=200:raise SourceRejected(body.get('status') if isinstance(body,dict) else None)
            result=price_parse(symbol,body.get('data',[]),today,time.time())
            results['finmind_prices']={'status':'ok','date':result['date'],'history_count':result['history_count'],'ma60_available':result['ma60'] is not None}
        except Exception as exc:results['finmind_prices']={'status':'failed',**describe(exc,'FinMind台股備援日線')}
    else:results['finmind_prices']={'status':'not_configured','reason':'未設定FINMIND_TOKEN，沒有下載'}
    return {'symbol':symbol,'requests':count,'sources':results,'ttm_eps_verified':False,
        'note':'只核對本次來源連線與解析，不寫入資料庫；成功不等於所有TTM／年度欄位齊全。'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--symbol',default='2330.TW');args=parser.parse_args()
    result=diagnose(args.symbol,token=os.getenv('FINMIND_TOKEN','').strip())
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if any(value.get('status')=='failed' for value in result['sources'].values()):raise SystemExit(1)


if __name__=='__main__':main()
