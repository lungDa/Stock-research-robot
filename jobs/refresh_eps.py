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
POLICY_VERSION=2


def transient(error_code):
    return error_code in ('timeout','connection','http_500','http_502','http_503','http_504')


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
            # One-time migration: an old two-second timeout must not block the
            # new policy for an entire day. Never bypass rejection/format cooldowns.
            migrate=old.get('policy_version',0)<POLICY_VERSION and old.get('status')=='failed' and transient(old.get('error_code'))
            if now<old.get('next_attempt',0) and not migrate:continue
            if not source_slot('twse_eps',12):return {'state':'limited','eps_requests':0}
            put('eps:cursor',{'value':i+1})
            put(key,{**old,'next_attempt':now+300,'last_attempt':now,'policy_version':POLICY_VERSION})
            try:
                result=fetch(symbol,local_now().date())
                previous=get('eps:official:'+symbol,{})
                rows={**previous.get('rows',{}),**result['rows']}
                put('eps:official:'+symbol,{**result,'rows':rows,'updated_at':datetime.now(timezone.utc).isoformat()})
                put(key,{'status':'ok','next_attempt':now+7*86400,'last_success':now,
                         'report_date':result['report_date'],'years':sorted(rows),
                         'policy_version':POLICY_VERSION,'transient_failures':0})
                return {'state':'updated','eps_requests':1,'symbol':symbol}
            except Exception as exc:
                # Fixed error: never expose a remote response, user, or credential.
                detail=describe(exc,'TWSE年度EPS PDF')
                attempts=min(8,old.get('transient_failures',0)+1) if transient(detail['error_code']) else 0
                delay=min(300*3**(attempts-1),3*3600) if attempts else 86400
                put(key,{**old,'status':'failed','last_attempt':now,'next_attempt':now+delay,
                         'policy_version':POLICY_VERSION,'transient_failures':attempts,**detail})
                return {'state':'failed','eps_requests':1,'symbol':symbol}
        return {'state':'cached','eps_requests':0}


if __name__=='__main__':print(run())
