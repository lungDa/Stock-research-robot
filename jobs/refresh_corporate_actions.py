"""Bounded free event downloads sharing the existing FinMind daily budget."""
import os, time, re
from datetime import timedelta
from app.db import init_db, get, put, leased
from app.providers.annual_free import FINMIND
from app.providers.corporate_actions import FEEDS, compact, request_parameters
from app.providers.bounded_http import fetch_json
from app.providers.finmind_batch import SourceRejected
from app.services.freshness import local_now
from app.services.data_queue import requested, source_slot
from app.services.accounts import member_users
from app.services.watchlist import watches
from app.providers.date_windows import covers


def run(symbols=None, max_requests=2):
    init_db(); token=os.getenv('FINMIND_TOKEN','').strip()
    if not token:return {'state':'not_configured','action_requests':0}
    today=local_now().date();start=str(today-timedelta(days=180));end=str(today)
    now=time.time();count=failed=0
    with leased('corporate:worker',180) as owned:
        if not owned:return {'state':'busy','action_requests':0}
        market_symbol=None
        if symbols is None:
            symbols=list(requested())+[s for u in member_users() for s in watches(u)]+os.getenv('ANNUAL_SYMBOLS','').split(',')
            from app.providers.universe import load
            universe=sorted(s for s in load() if s.endswith(('.TW','.TWO')))
            if universe:
                market_cursor=get('corporate:market_cursor',{}).get('value',0)%len(universe)
                market_symbol=universe[market_cursor]
                symbols.append(market_symbol)
        from app.providers.market import normalize
        symbols=sorted({normalize(s) for s in symbols if s.strip()})
        tasks=[(s,f) for s in symbols if re.fullmatch(r'\d{4,6}[A-Z]?\.(TW|TWO)',s) for f in FEEDS]
        if not tasks:return {'state':'idle','action_requests':0}
        cursor=get('corporate:cursor',{}).get('value',0)%len(tasks)
        for offset in range(len(tasks)):
            if count >= max(1,min(int(max_requests),2)):break
            if now < get('annual:source:finmind',{}).get('next_attempt',0):break
            i=(cursor+offset)%len(tasks);symbol,feed=tasks[i]
            key='corporate:feed:'+symbol+':'+feed;old=get(key,{})
            put('corporate:cursor',{'value':(i+1)%len(tasks)})
            if now < old.get('next_attempt',0):continue
            if not source_slot('finmind',100):break
            count+=1
            put(key,{**old,'next_attempt':now+3600})
            try:
                payload=fetch_json(FINMIND,request_parameters(feed, symbol, start, end),headers={'Authorization':'Bearer '+token},
                    max_bytes=262144,seconds=6)
                if not isinstance(payload,dict) or payload.get('status')!=200:
                    raise SourceRejected(payload.get('status') if isinstance(payload,dict) else None)
                events=compact(feed,payload.get('data'),symbol,start,end)
                put(key,{'status':'ok','events':events,'coverage_windows':[{'start':start,'end':end,'at':now}],
                         'source':'FinMind / '+feed,'as_of':end,'next_attempt':now+6*3600})
            except Exception as exc:
                failed+=1
                # Retain the old verified interval, but never extend it after failure.
                put(key,{**old,'next_attempt':now+3600,'last_failure':type(exc).__name__})
                if getattr(exc,'status',None) in (401,403,429):
                    put('annual:source:finmind',{'next_attempt':now+86400})
        result={'state':'partial' if failed else 'finished','action_requests':count,'failed_feeds':failed}
        if market_symbol and all(covers(get('corporate:feed:'+market_symbol+':'+f,{}).get('coverage_windows',[]),start,end) for f in FEEDS):
            put('corporate:market_cursor',{'value':(market_cursor+1)%len(universe)})
        put('jobs:corporate_actions',result)
        return result


if __name__ == '__main__':print(run())
