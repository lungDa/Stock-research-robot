"""At most two US EOD requests; shared cache, same FinMind source cooldown."""
import os,re,time
from datetime import timedelta
from app.db import init_db,get,put
from app.providers.bounded_http import fetch_json
from app.providers.annual_free import FINMIND
from app.providers.us_daily import parse
from app.services.accounts import member_users
from app.services.watchlist import watches
from app.services.freshness import local_now


def run():
    from app.db import leased
    init_db()
    with leased('annual:worker',180) as owned:
        if not owned:return
        return _run()


def _run():
    init_db();now=time.time();today=local_now().date()
    token=os.getenv('FINMIND_TOKEN','').strip()
    if not token:
        print('US日線：FINMIND_TOKEN未設定，略過。');return
    symbols=list(dict.fromkeys([s for u in member_users() for s in watches(u)]+
        [s.strip().upper() for s in os.getenv('ANNUAL_SYMBOLS','').split(',') if s.strip()]))
    from app.services.data_queue import requested,source_slot
    symbols=list(dict.fromkeys(symbols+list(requested())))
    symbols=sorted(s for s in symbols if re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',s) and not s.endswith(('.TW','.TWO')))
    if not symbols:
        print('US日線：沒有指定美股，略過。');return
    cursor=get('usdaily:cursor',{'value':0})['value']%len(symbols);count=0;updated=0
    for offset in range(len(symbols)):
        if count>=2 or now<get('annual:source:finmind',{}).get('next_attempt',0):break
        i=(cursor+offset)%len(symbols);symbol=symbols[i]
        put('usdaily:cursor',{'value':(i+1)%len(symbols)})
        state=get('usdaily:state:'+symbol,{})
        if now<state.get('next_attempt',0):continue
        if not source_slot('finmind',100):break
        put('usdaily:state:'+symbol,{'next_attempt':now+86400})
        try:
            count+=1
            payload=fetch_json(FINMIND,{'dataset':'USStockPrice','data_id':symbol,
                'start_date':str(today-timedelta(days=400)),'end_date':str(today)},
                headers={'Authorization':'Bearer '+token},max_bytes=262144,seconds=6)
            if payload.get('status')!=200:
                put('annual:source:finmind',{'next_attempt':now+86400})
                raise ValueError('source rejected')
            previous=get('quote:'+symbol,{})
            annual=get('annual:shared:'+symbol,{}).get('rows',{})
            if previous.get('kind') not in ('STOCK','ETF') and any(r.get('provenance')=='SEC_10K' for r in annual.values()):
                previous={**previous,'kind':'STOCK'}
            data=parse(symbol,payload.get('data',[]),today,previous);data['cached_at']=now
            put('usdaily:quote:'+symbol,data);updated+=1
        except Exception as exc:
            code=getattr(getattr(exc,'response',None),'status_code',None)
            if code in (401,403,429):put('annual:source:finmind',{'next_attempt':now+86400})
            print('US日線未完成：'+symbol+'；保留舊快取，隔日再試。')
    print({'us_price_requests':count,'us_price_updated':updated})


if __name__=='__main__':run()
