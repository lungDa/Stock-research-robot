"""Bounded, resumable annual-data worker. No network calls from ratings/UI.
At most eight HTTP requests / ~60 seconds per run; 1 MiB per response.
"""
import os, re, time
from datetime import datetime, timezone,timedelta
from app.db import init_db, get, put
from app.providers.bounded_http import fetch_json
from app.providers.annual_free import (FINMIND, SEC, TW_DATASETS, SEC_CONCEPTS,
                                      taiwan_rows, taiwan_fund_profile, sec_records, us_rows,TW_CASH_SCHEMA)
from app.providers.market import normalize
from app.services.accounts import member_users
from app.services.watchlist import watches
from app.services.freshness import local_now
from app.providers.trailing import sec_period_records,us_trailing,taiwan_trailing,taiwan_eps_four_quarters
PERIOD_SCHEMA=1
TW_EPS_SCHEMA=1


def compact(dataset, records, code):
    # Persist only needed columns; do not cache the full financial statements.
    if not isinstance(records,list): raise ValueError('Invalid data array')
    tags={'EPS','Revenue','IncomeAfterTaxes','Equity','CashFlowsFromOperatingActivities','PropertyAndPlantAndEquipment'}
    cols={'date','stock_id','type','value','origin_name','year','CashDividendPaymentDate',
          'CashExDividendTradingDate','CashEarningsDistribution','CashStatutorySurplus','close',
          'StockExDividendTradingDate','StockEarningsDistribution','StockStatutorySurplus'}
    result=[]
    for r in records:
        if not isinstance(r,dict) or str(r.get('stock_id'))!=code:continue
        if dataset in TW_DATASETS[:3] and r.get('type') not in tags:
            # Keep dividend cash-flow labels before parsing; preserve diagnostics
            # instead of losing every unfamiliar source label at compaction.
            if dataset!=TW_DATASETS[2]:continue
        result.append({k:v for k,v in r.items() if k in cols})
    return result


def run(symbols=None,max_requests=8,seconds=48,query=False):
    from app.db import leased
    init_db()
    with leased('annual:worker',60) as owned:
        if not owned:return {'state':'busy','annual_requests':0,'updated_symbols':0,'failed_feeds':0}
        result=_run(symbols,max_requests,seconds,query)
        if not query:
            put('jobs:annual',{'updated_at':datetime.now(timezone.utc).isoformat(),**(result or {})})
        return result


def _run(symbols=None,max_requests=8,seconds=48,query=False):
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
        from app.services.data_queue import requested
        for s in requested():
            if s not in symbols:symbols.append(s)
    if not explicit and os.getenv('ANNUAL_UNIVERSE_BATCH','').strip() == '1':
        # Cover the whole TWSE/TPEx universe gradually without loading every
        # company/feed pair into one invocation or blocking personal requests.
        from app.providers.universe import load as load_universe
        try:
            universe=sorted(set(s for s in load_universe() if s.endswith(('.TW','.TWO'))))
        except Exception:
            universe=[]
        if universe:
            start=int(get('annual:universe_cursor',{'value':0}).get('value',0))%len(universe)
            # Half the market batch follows the partial-coverage priority
            # snapshot; the other half remains a full-market round robin.
            # This avoids starving stocks absent from the diagnostic snapshot.
            from app.services.annual_priority import choose_market_batch
            snapshot=get('v27:priority:six_factor_provisional',{})
            if snapshot.get('scope') != 'SIX_FACTOR_PROVISIONAL':
                snapshot=get('v26:priority:partial',{})
            batch, advanced=choose_market_batch(universe,start,snapshot,now=now)
            put('annual:universe_cursor',{'value':(start+advanced)%len(universe)})
            for s in batch:
                if s not in symbols:
                    symbols.append(s)
    if not symbols:
        print('年度資料：尚無追蹤清單或可用市場母體，略過。');return
    # FinMind company financial statements are not applicable to ETF/fund
    # securities or alphanumeric exchange codes. Keep ordinary 4-digit shares.
    def eligible(symbol):
        if not symbol.endswith(('.TW', '.TWO')):
            return True
        code = symbol.split('.')[0]
        if not re.fullmatch(r'\d{4}', code):
            return False
        quote = get('quote:' + symbol, {})
        if quote.get('kind') in ('ETF', 'ETN', 'FUND'):
            return False
        return True
    symbols = [symbol for symbol in symbols if eligible(symbol)]
    if not symbols:
        return {'annual_requests': 0, 'updated_symbols': 0, 'failed_feeds': 0, 'state': 'no_eligible_symbols'}
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
    # Round-robin across companies, then feeds; retain the persisted cursor.
    tasks=sorted(tasks,key=lambda pair:((list(TW_DATASETS).index(pair[1]) if pair[1] in TW_DATASETS else list(SEC_CONCEPTS).index(pair[1])),pair[0]))
    count=0; touched=set(); failures=0
    def download(url,params=None,headers=None):
        nonlocal count
        if count>=max_requests or time.monotonic()-started>=seconds:raise StopIteration
        from app.services.data_queue import source_slot
        source='finmind' if url==FINMIND else 'sec'
        if not source_slot(source,100 if source=='finmind' else 60):raise StopIteration
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
        eps_migration=source=='finmind' and feed==TW_DATASETS[0] and state.get('eps_schema',0)<TW_EPS_SCHEMA
        migration=eps_migration or (feed==TW_DATASETS[2] and state.get('schema',0)<TW_CASH_SCHEMA) or ((feed==TW_DATASETS[3] or (source=='sec' and feed in ('eps','net_income','equity'))) and state.get('period_schema',0)<PERIOD_SCHEMA)
        if now<state.get('next_attempt',0) and not migration:continue
        if eps_migration:
            # Old versions discarded EPS. Refill recent quarters first without
            # erasing older financial rows or requesting eleven years again.
            start=today-timedelta(days=730)
            rest=[]
            for window in state.get('pending_windows',[]):
                if window['start']<str(start):rest.append({'start':window['start'],'end':min(window['end'],str(start-timedelta(days=1)))})
            if not state.get('records') and not rest:
                rest=[{'start':f'{today.year-11}-01-01','end':str(start-timedelta(days=1))}]
            state={**state,'pending_windows':[{'start':str(start),'end':str(today)}]+rest,'eps_schema':TW_EPS_SCHEMA,'next_attempt':0}
        # Reserve before request, including failures/interruption; no immediate retries.
        put(statekey,{**state,'next_attempt':now+86400,'schema':TW_CASH_SCHEMA,'period_schema':PERIOD_SCHEMA})
        try:
            period_records=[]
            if symbol.endswith(('.TW','.TWO')):
                from app.providers.finmind_batch import batch
                result,changed=batch(symbol,feed,state,today,download,compact,token)
                result.update(schema=TW_CASH_SCHEMA,period_schema=PERIOD_SCHEMA)
                put(statekey,result)
                if changed:touched.add(symbol)
                continue
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
        except StopIteration:
            put(statekey,state)
            break
        except Exception as exc:
            failures+=1
            code=getattr(exc,'status',None) or getattr(getattr(exc,'response',None),'status_code',None)
            if code in (401,403,429):put('annual:source:'+source,{'next_attempt':now+86400})
            from app.providers.bounded_http import ResourceLimitError
            reason=('來源回應超過本批大小或時間預算' if isinstance(exc,ResourceLimitError) else
                    '來源拒絕或限流，等待冷卻' if code in (401,403,429) else
                    '來源未提供可用紀錄、連線失敗或格式未通過核對')
            put(statekey,{**state,'next_attempt':now+86400,'status':'failed','last_error':reason,
                          'last_attempt':now,'schema':TW_CASH_SCHEMA,'period_schema':PERIOD_SCHEMA})
            # No exception strings: remote URLs or headers must not expose tokens.
            print('年度資料來源未完成：'+symbol+' / '+feed+'；保留舊快取並冷卻一天。')
    for symbol in touched:
        feed_states={feed:get('annual:feed:'+symbol+':'+feed,{}) for feed in TW_DATASETS} if symbol.endswith(('.TW','.TWO')) else {}
        coverage={feed:state['coverage_windows'] for feed,state in feed_states.items() if 'coverage_windows' in state}
        feeds={feed:state.get('records',[]) for feed,state in feed_states.items()} if symbol.endswith(('.TW','.TWO')) else {
            m:get('annual:feed:'+symbol+':'+m,{}).get('records',{}) for m in SEC_CONCEPTS}
        rows=taiwan_rows(symbol,feeds,today,coverage) if symbol.endswith(('.TW','.TWO')) else us_rows(get('annual:cik:'+symbol)['cik'],feeds,today)
        # Recompute from successful feed snapshots; absent feeds remain missing.
        profile=taiwan_fund_profile(symbol,feeds.get(TW_DATASETS[3],[]),today) if symbol.endswith(('.TW','.TWO')) else {}
        if profile:
            profile['fetched_at']=feed_states.get(TW_DATASETS[3],{}).get('at',0)
            if TW_DATASETS[3] in coverage:profile['coverage_windows']=coverage[TW_DATASETS[3]]
        if symbol.endswith(('.TW','.TWO')):
            trailing=taiwan_trailing(symbol,feeds,today)
            quarterly=taiwan_eps_four_quarters(symbol,feeds.get(TW_DATASETS[0],[]),today)
            if quarterly:trailing['eps_four_quarter_sum']=quarterly
        else:
            trailing=us_trailing({m:get('annual:feed:'+symbol+':'+m,{}).get('period_records',[]) for m in ('eps','net_income','equity')},today)
        put('annual:shared:'+symbol,{'rows':rows,'updated_at':datetime.now(timezone.utc).isoformat(),
            'trailing':trailing,
            'fund_profile':profile,
            'status':'partial','notes':['分批補齊；無資料不補零。美股EPS以USD/股計，台股以TWD/股計。',
                'ETF不套用公司EPS與ROE；費用率與完整配息仍須可核對來源。']})
    summary={'annual_requests':count,'updated_symbols':len(touched),'failed_feeds':failures}
    print(summary)
    return summary


if __name__=='__main__':run()
