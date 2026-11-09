"""Continue official Taiwan monthly history separately from quote refreshes."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from app.db import get,put,init_db,leased
from app.providers.taiwan_official import month


def months(today):
    first=today.replace(day=1)
    return [(pd.Timestamp(first)-pd.offsets.MonthBegin(i)).date() for i in range(4)]


def run():
    init_db()
    with leased('history:worker',90) as owned:
        if not owned:return {'state':'busy'}
        from app.services.data_queue import requested
        from app.services.accounts import member_users
        from app.services.watchlist import watches
        symbols=list(dict.fromkeys(list(requested())+[s for u in member_users() for s in watches(u)]))
        symbols=[s for s in symbols if s.endswith(('.TW','.TWO'))]
        if not symbols:return {'state':'idle','attempted':0}
        today=datetime.now(ZoneInfo('Asia/Taipei')).date();now=time.time()
        cursor=get('history:cursor',{}).get('cursor',0)%len(symbols)
        attempted=completed=0;started=time.monotonic()
        for i in range(len(symbols)):
            if attempted>=2 or time.monotonic()-started>15:break
            symbol=symbols[(cursor+i)%len(symbols)];code,market=symbol.rsplit('.',1)
            put('history:cursor',{'cursor':(cursor+i+1)%len(symbols)})
            if now<get('history:state:'+symbol,{}).get('next_attempt',0):continue
            plan=months(today)
            records={d:get(f'official:month:{market}:{code}:{d:%Y%m}') for d in plan}
            # Missing older months come before repeatedly expiring current months.
            missing=[d for d in plan if not records[d]]
            expired=[d for d in plan if records[d] and now-records[d]['at']>=(3600 if d==plan[0] else 7*86400)]
            pending=missing+expired
            if not pending:continue
            attempted+=1
            try:
                month(code,market,pending[0],today);completed+=1
                cached=get('quote:'+symbol)
                if cached:
                    from app.providers.taiwan_official import refresh_cached_history
                    from app.providers.fundamentals import attach
                    from app.services.analysis import enrich
                    rebuilt=refresh_cached_history(cached)
                    if rebuilt!=cached:put('quote:'+symbol,enrich(attach(rebuilt)))
                put('history:state:'+symbol,{'next_attempt':0,'remaining_months':len(pending)-1,'state':'partial' if len(pending)>1 else 'finished'})
            except Exception:
                put('history:state:'+symbol,{'next_attempt':now+300,'remaining_months':len(pending),'state':'partial'})
        result={'state':'partial' if completed<attempted else 'finished','attempted':attempted,'completed':completed}
        put('jobs:history',result);return result


if __name__=='__main__':print(run())
