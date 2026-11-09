"""One verified TWSE company profile per run; no inferred quarterly EPS."""
import os,time,re
from datetime import datetime,timezone
from app.db import init_db,get,put,leased
from app.services.data_queue import requested,source_slot
from app.services.accounts import member_users
from app.services.watchlist import watches
from app.services.freshness import local_now
from app.providers.market import normalize
from app.providers.twse_eps import fetch
from app.providers.source_errors import describe


def run(symbols=None):
    init_db();now=time.time()
    with leased('annual:worker',180) as owned:
        if not owned:return {'state':'busy','eps_requests':0}
        if symbols is None:
            symbols=list(requested())+[s for u in member_users() for s in watches(u)]
            symbols+=[s.strip() for s in os.getenv('ANNUAL_SYMBOLS','').split(',') if s.strip()]
        symbols=sorted({normalize(s) for s in symbols if s.strip()})
        symbols=[s for s in symbols if re.fullmatch(r'\d{4}\.TW',s) and get('quote:'+s,{}).get('kind')!='ETF']
        if not symbols:return {'eps_requests':0}
        cursor=get('eps:cursor',{'value':0})['value']%len(symbols)
        for offset in range(len(symbols)):
            i=(cursor+offset)%len(symbols);symbol=symbols[i];key='eps:state:'+symbol
            old=get(key,{})
            if now<old.get('next_attempt',0):continue
            if not source_slot('twse_eps',12):return {'state':'limited','eps_requests':0}
            put('eps:cursor',{'value':i+1})
            put(key,{**old,'next_attempt':now+86400,'last_attempt':now})
            try:
                result=fetch(symbol,local_now().date())
                previous=get('eps:official:'+symbol,{})
                rows={**previous.get('rows',{}),**result['rows']}
                put('eps:official:'+symbol,{**result,'rows':rows,'updated_at':datetime.now(timezone.utc).isoformat()})
                put(key,{'status':'ok','next_attempt':now+7*86400,'last_success':now,
                         'report_date':result['report_date'],'years':sorted(rows)})
                return {'state':'updated','eps_requests':1,'symbol':symbol}
            except Exception as exc:
                # Fixed error: never expose a remote response, user, or credential.
                put(key,{**old,'status':'failed','last_attempt':now,'next_attempt':now+86400,
                         **describe(exc,'TWSE年度EPS PDF')})
                return {'state':'failed','eps_requests':1,'symbol':symbol}
        return {'state':'cached','eps_requests':0}


if __name__=='__main__':print(run())
