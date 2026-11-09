"""At most two short Taiwan daily requests, sharing the FinMind budget."""
import os,time,re
from datetime import timedelta
from app.db import init_db,get,put,leased
from app.providers.bounded_http import fetch_json
from app.providers.annual_free import FINMIND,TW_DATASETS
from app.providers.finmind_batch import SourceRejected
from app.providers.source_errors import describe
from app.providers.tw_daily import parse
from app.services.freshness import local_now
from app.services.data_queue import requested,source_slot
from app.services.accounts import member_users
from app.services.watchlist import watches


def run(symbols=None,max_requests=2):
    init_db();now=time.time();today=local_now().date();count=updated=failed=0
    token=os.getenv('FINMIND_TOKEN','').strip()
    if not token:return {'state':'not_configured','tw_price_requests':0}
    max_requests=max(1,min(int(max_requests),2))
    with leased('annual:worker',180) as owned:
        if not owned:return {'state':'busy','tw_price_requests':0}
        if symbols is None:
            symbols=list(requested())+[s for u in member_users() for s in watches(u)]+os.getenv('ANNUAL_SYMBOLS','').split(',')
        from app.providers.market import normalize
        symbols=sorted({normalize(s) for s in symbols if s.strip()})
        symbols=[s for s in symbols if re.fullmatch(r'\d{4,6}[A-Z]?\.(TW|TWO)',s)]
        if not symbols:return {'state':'idle','tw_price_requests':0}
        cursor=get('twdaily:cursor',{}).get('value',0)%len(symbols)
        for offset in range(len(symbols)):
            if count>=max_requests or now<get('annual:source:finmind',{}).get('next_attempt',0):break
            i=(cursor+offset)%len(symbols);symbol=symbols[i];key='twdaily:state:'+symbol
            put('twdaily:cursor',{'value':(i+1)%len(symbols)})
            if now<get(key,{}).get('next_attempt',0):continue
            if not source_slot('finmind',100):break
            count+=1
            # Reserve before HTTP. Failures retry in an hour, never per page poll.
            put(key,{'status':'running','next_attempt':now+3600})
            try:
                payload=fetch_json(FINMIND,{'dataset':TW_DATASETS[4],'data_id':symbol.split('.')[0],
                    'start_date':str(today-timedelta(days=160)),'end_date':str(today)},
                    headers={'Authorization':'Bearer '+token},max_bytes=262144,seconds=6)
                if not isinstance(payload,dict) or payload.get('status')!=200:raise SourceRejected(payload.get('status') if isinstance(payload,dict) else None)
                result=parse(symbol,payload.get('data',[]),today,now,get('quote:'+symbol,{}))
                put('twdaily:quote:'+symbol,result);updated+=1
                put(key,{'status':'ok','date':result['date'],'history_count':result['history_count'],
                         'next_attempt':now+6*3600,'last_success':now})
            except Exception as exc:
                failed+=1;status=getattr(exc,'status',None) or getattr(getattr(exc,'response',None),'status_code',None)
                if status in (401,403,429):put('annual:source:finmind',{'next_attempt':now+86400})
                detail=describe(exc,'台股備援日線')
                if isinstance(exc,SourceRejected):detail={'error_code':'source_rejected','stage':'台股備援日線','reason':'FinMind拒絕本次資料集請求'}
                put(key,{'status':'failed','next_attempt':now+3600,'last_attempt':now,**detail})
        return {'state':'partial' if failed else 'finished','tw_price_requests':count,'updated_symbols':updated,'failed_feeds':failed}


if __name__=='__main__':print(run())
