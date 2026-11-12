"""交易日11:30/19:30排名，固定outbox及retry key防重送。"""
import argparse,time,uuid
from app.db import init_db,get,put,leased
from app.services.freshness import local_now,TAIPEI
from app.services.accounts import member_users,can_use_personal
from app.services.market_recommendations import preferences,is_session,target_day,collect,rank,messages
from app.services.multifactor import settings_for
from app.channels.line import quota,push

def deliver(user,key,texts,dry_run,remaining):
    if dry_run:return remaining
    state=get(key)
    if state is None:
        if remaining<len(texts)+5:raise RuntimeError('LINE配額不足，排名報告未發送')
        state={'created_at':time.time(),'messages':[{'text':t,'retry_key':str(uuid.uuid4()),'sent':False} for t in texts]};put(key,state)
    if time.time()-state['created_at']>23*3600:raise RuntimeError('排名送出狀態逾期，停止重送')
    for entry in state['messages']:
        if entry['sent']:continue
        if remaining<=5:raise RuntimeError('LINE配額不足，保留未確認訊息')
        push(user,entry['text'],entry['retry_key']);entry['sent']=True;remaining-=1;put(key,state)
    return remaining

def run(slot,dry_run=True,now=None):
    init_db();now=(now or local_now()).astimezone(TAIPEI);today=now.date()
    if slot not in ('morning','evening'):raise ValueError('slot錯誤')
    if not dry_run:
        start=(11,30) if slot=='morning' else (19,30);minute=now.hour*60+now.minute
        if not start[0]*60+start[1]<=minute<start[0]*60+start[1]+60:raise RuntimeError('超過本時段一小時發送窗口，不補發過期排名')
    if not is_session(today):return {'status':'closed','date':str(today)}
    with leased('recommendations:worker',seconds=840) as acquired:
        if not acquired:raise RuntimeError('另一排名工作執行中')
        deadline=time.monotonic()+600
        users=[u for u in member_users() if can_use_personal(u) and preferences(u)['enabled']]
        if not users:return {'status':'no_subscribers'}
        target=target_day(today,slot)
        from app.providers.taiwan_official import snapshot
        from jobs.refresh_universe import build
        from app.providers.universe import load
        build();snapshots={}
        for market in ('TW','TWO'):
            try:
                latest=snapshot(market)
                days={v['date'] for k,v in latest.items() if k!='_meta' and isinstance(v,dict) and 'date' in v}
                for day in days:
                    # Store observed closes for the morning run if source rolls over early.
                    saved={k:v for k,v in latest.items() if k=='_meta' or v.get('date')==day}
                    put('recommendations:prices:'+market+':'+day,saved)
                snapshots[market]=latest if str(target) in days else get('recommendations:prices:'+market+':'+str(target),{})
            except Exception:
                snapshots[market]=get('recommendations:prices:'+market+':'+str(target),{})
        for market,quotes in snapshots.items():
            dates={v['date'] for k,v in quotes.items() if k!='_meta' and isinstance(v,dict) and 'date' in v}
            if str(target) not in dates:raise RuntimeError(market+'未提供目標行情日，停止排名推播')
        symbols=sorted(set(s for s in load() if s.endswith(('.TW','.TWO'))))
        partial=get('universe:scope',{}).get('partial',True) or any(not v.get('_meta',{}).get('complete',True) for v in snapshots.values())
        remaining=0 if dry_run else quota();reports=[]
        for user in users:
            if time.monotonic()>deadline:raise TimeoutError('排名工作超過時間預算')
            key=f'recommendations:outbox:{today}:{slot}:{user}';pending=get(key)
            if pending and not dry_run:
                remaining=deliver(user,key,[],False,remaining);continue
            items,coverage=collect(symbols,snapshots,target,user,deadline)
            report={**rank(items,settings_for(user),today),'coverage':coverage,'target_date':str(target),'date':str(today),'slot':slot,'slot_label':'11:30' if slot=='morning' else '19:30','universe_partial':partial,'generated_at':now.isoformat()}
            texts=messages(report);put('recommendations:'+('preview:' if dry_run else 'latest:')+user,report)
            remaining=deliver(user,key,texts,dry_run,remaining)
            # Independent opt-in four-mode outbox; never alter existing ranking.
            from app.day_trader.reporting import preferences as four_preferences, latest as four_latest, summary as four_summary
            if four_preferences(user).get('enabled'):
                four_report=four_latest(user)
                if four_report.get('as_of')==str(target):
                    four_text=four_summary(four_report)
                    if four_text:
                        four_key=f'four_rankings:outbox:{today}:{slot}:{user}'
                        remaining=deliver(user,four_key,[four_text],dry_run,remaining)

            reports.append({'matched':report['matched'],'round':report['round'],'coverage':coverage,'messages':len(texts)})
        return {'status':'preview' if dry_run else 'sent','reports':reports}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--slot',choices=['morning','evening'],required=True);p.add_argument('--send',action='store_true');a=p.parse_args()
    print(run(a.slot,dry_run=not a.send))
