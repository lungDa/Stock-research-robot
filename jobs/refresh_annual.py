"""Bounded, resumable annual-data worker. No network calls from ratings/UI.
At most eight HTTP requests / ~60 seconds per run; 1 MiB per response.
"""
import os, re, time
from datetime import datetime, timezone
from app.db import init_db, get, put
from app.providers.bounded_http import fetch_json
from app.providers.annual_free import (FINMIND, SEC, TW_DATASETS, SEC_CONCEPTS,
                                      taiwan_rows, taiwan_fund_profile, sec_records, us_rows,TW_CASH_SCHEMA)
from app.providers.market import normalize
from app.services.accounts import member_users
from app.services.watchlist import watches
from app.services.freshness import local_now
from app.providers.trailing import sec_period_records,us_trailing,taiwan_trailing
PERIOD_SCHEMA=1


def compact(dataset, records, code):
    # Persist only needed columns; do not cache the full financial statements.
    if not isinstance(records,list): raise ValueError('Invalid data array')
    tags={'Revenue','IncomeAfterTaxes','Equity','CashFlowsFromOperatingActivities','PropertyAndPlantAndEquipment'}
    cols={'date','stock_id','type','value','origin_name','year','CashDividendPaymentDate',
          'CashExDividendTradingDate','CashEarningsDistribution','CashStatutorySurplus','close',
          'StockExDividendTradingDate','StockEarningsDistribution','StockStatutorySurplus'}
    result=[]
    for r in records:
        if not isinstance(r,dict) or str(r.get('stock_id'))!=code:continue
        if dataset in TW_DATASETS[:3] and r.get('type') not in tags:
            # Keep dividend cash-flow labels before parsing; preserve diagnostics
            # instead of losing every unfamiliar source label at compaction.
            if dataset!=TW_DATASETS[2] or not any(s in str(r.get('origin_name','')) for s in ('股利','股息')):continue
        result.append({k:v for k,v in r.items() if k in cols})
    return result


def run(symbols=None,max_requests=8,seconds=48,query=False):
    init_db(); started=time.monotonic(); now=time.time(); today=local_now().date()
    token=os.getenv('FINMIND_TOKEN','').strip()
    sec_agent=os.getenv('SEC_USER_AGENT','').strip()
    if sec_agent and not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+',sec_agent):
        print('年度資料：SEC_USER_AGENT須包含維護者聯絡Email；本次不請求SEC。')
        sec_agent=''
    max_requests=max(1,min(int(max_requests),8));seconds=max(1,min(float(seconds),48))
    explicit=symbols is not None
    symbols=([normalize(s) for s in symbols] if explicit else list(dict.fromkeys(normalize(s) for u in member_users() for s in watches(u))))
    # Optional operator-selected symbols allow bootstrapping before adding watches.
    for s in ([] if explicit else os.getenv('ANNUAL_SYMBOLS','').split(',')):
        if s.strip():
            s=normalize(s)
            if s not in symbols:symbols.append(s)
    if not explicit:
        for s,stamp in get('annual:requested',{}).items():
            if now-stamp<14*86400 and s not in symbols:symbols.append(s)
    if not symbols:
        print('年度資料：尚無追蹤清單或ANNUAL_SYMBOLS，略過。');return
    symbols=sorted(symbols)
    # Cursor across symbol/feed pairs prevents one slow company starving others.
    tasks=[]
    for s in symbols:
        if s.endswith(('.TW','.TWO')) and token:
            tasks.extend((s,d) for d in TW_DATASETS)
        elif '.' not in s and sec_agent:
            quote=get('quote:'+s,{})
            if quote.get('kind')!='ETF':tasks.extend((s,m) for m in SEC_CONCEPTS)
    if not tasks:
        print('年度資料：未設定來源憑證／識別資訊，或僅有不支援的ETF；不發請求。');return
    count=0; touched=set(); failures=0
    def download(url,params=None,headers=None):
        nonlocal count
        if count>=max_requests or time.monotonic()-started>=seconds:raise StopIteration
        count+=1
        return fetch_json(url,params,headers=headers,max_bytes=1048576,seconds=6)
    cursor_key='annual:query_cursor:'+symbols[0] if query else 'annual:cursor'
    cursor=get(cursor_key,{'value':0})['value']%len(tasks)
    for offset in range(len(tasks)):
        if count>=max_requests or time.monotonic()-started>=seconds:break
        i=(cursor+offset)%len(tasks); symbol,feed=tasks[i]
        source='finmind' if symbol.endswith(('.TW','.TWO')) else 'sec'
        if now<get('annual:source:'+source,{}).get('next_attempt',0):continue
        statekey='annual:feed:'+symbol+':'+feed; state=get(statekey,{})
        put(cursor_key,{'value':(i+1)%len(tasks)})
        migration=(feed==TW_DATASETS[2] and state.get('schema',0)<TW_CASH_SCHEMA) or ((feed==TW_DATASETS[3] or (source=='sec' and feed in ('eps','net_income','equity'))) and state.get('period_schema',0)<PERIOD_SCHEMA)
        if now<state.get('next_attempt',0) and not migration:continue
        # Reserve before request, including failures/interruption; no immediate retries.
        put(statekey,{**state,'next_attempt':now+86400,'schema':TW_CASH_SCHEMA,'period_schema':PERIOD_SCHEMA})
        try:
            period_records=[]
            if symbol.endswith(('.TW','.TWO')):
                payload=download(FINMIND,{'dataset':feed,'data_id':symbol.split('.')[0],
                    'start_date':f'{today.year-11}-01-01','end_date':today.isoformat()},
                    {'Authorization':'Bearer '+token})
                if payload.get('status')!=200:
                    put('annual:source:finmind',{'next_attempt':now+86400})
                    raise ValueError('FinMind unavailable')
                records=compact(feed,payload.get('data'),symbol.split('.')[0])
            else:
                # SEC contact goes only to SEC. No token or identity is printed.
                index=get('annual:sec_tickers',{})
                if not index or now-index.get('at',0)>7*86400:
                    if now<get('annual:sec_index_retry',{}).get('at',0):continue
                    put('annual:sec_index_retry',{'at':now+86400})
                    raw=download('https://www.sec.gov/files/company_tickers.json',headers={'User-Agent':sec_agent})
                    mapping={str(r['ticker']).upper().replace('-','.'):str(r['cik_str']).zfill(10)
                             for r in raw.values() if isinstance(r,dict) and 'ticker' in r and 'cik_str' in r}
                    if not mapping:raise ValueError('Empty SEC ticker index')
                    index={'at':now,'mapping':mapping};put('annual:sec_tickers',index)
                cik=index['mapping'].get(symbol.replace('-','.'))
                if not cik:raise ValueError('SEC CIK not available')
                tag,unit=SEC_CONCEPTS[feed]
                payload=download(f'{SEC}CIK{cik}/us-gaap/{tag}.json',headers={'User-Agent':sec_agent})
                if str(payload.get('cik','')).zfill(10)!=cik:raise ValueError('SEC CIK mismatch')
                records=sec_records(payload,feed,today)
                if feed in ('eps','net_income','equity'):period_records=sec_period_records(payload,feed,unit,today)
                put('annual:cik:'+symbol,{'cik':cik})
            if not records:raise ValueError('No usable annual records; keep old snapshot')
            put(statekey,{'next_attempt':now+7*86400,'records':records,'at':now,'status':'ok','schema':TW_CASH_SCHEMA,
                'period_schema':PERIOD_SCHEMA,'period_records':period_records})
            if feed==TW_DATASETS[2]:
                print({'symbol':symbol,'cash_dividend_labels':sorted({str(r.get('origin_name','')) for r in records if '股利' in str(r.get('origin_name','')) or '股息' in str(r.get('origin_name',''))})[:20]})
            touched.add(symbol)
        except StopIteration:break
        except Exception as exc:
            failures+=1
            code=getattr(getattr(exc,'response',None),'status_code',None)
            if code in (401,403,429):put('annual:source:'+source,{'next_attempt':now+86400})
            put(statekey,{**state,'next_attempt':now+86400,'status':'failed','schema':TW_CASH_SCHEMA,'period_schema':PERIOD_SCHEMA})
            # No exception strings: remote URLs or headers must not expose tokens.
            print('年度資料來源未完成：'+symbol+' / '+feed+'；保留舊快取並冷卻一天。')
    for symbol in touched:
        feeds={feed:get('annual:feed:'+symbol+':'+feed,{}).get('records',[]) for feed in TW_DATASETS} if symbol.endswith(('.TW','.TWO')) else {
            m:get('annual:feed:'+symbol+':'+m,{}).get('records',{}) for m in SEC_CONCEPTS}
        rows=taiwan_rows(symbol,feeds,today) if symbol.endswith(('.TW','.TWO')) else us_rows(get('annual:cik:'+symbol)['cik'],feeds,today)
        # Recompute from successful feed snapshots; absent feeds remain missing.
        put('annual:shared:'+symbol,{'rows':rows,'updated_at':datetime.now(timezone.utc).isoformat(),
            'trailing':taiwan_trailing(symbol,feeds,today) if symbol.endswith(('.TW','.TWO')) else us_trailing({
                m:get('annual:feed:'+symbol+':'+m,{}).get('period_records',[]) for m in ('eps','net_income','equity')},today),
            'fund_profile':taiwan_fund_profile(symbol,feeds.get(TW_DATASETS[3],[]),today) if symbol.endswith(('.TW','.TWO')) else {},
            'status':'partial','notes':['分批補齊；無資料不補零。美股EPS以USD/股計，台股以TWD/股計。',
                'ETF不套用公司EPS與ROE；費用率與完整配息仍須可核對來源。']})
    summary={'annual_requests':count,'updated_symbols':len(touched),'failed_feeds':failures}
    print(summary)
    return summary


if __name__=='__main__':run()
