"""交易日11:30/19:30排名，固定outbox及retry key防重送。"""
import argparse,time,uuid
from app.db import init_db,get,put,leased
from app.services.freshness import local_now,TAIPEI
from app.services.accounts import member_users,can_use_personal
from app.services.market_recommendations import preferences,is_session,target_day,collect,rank,messages
from app.services.multifactor import settings_for
from app.channels.line import quota,push,push_message
from app.config import settings
from app.services.recommendation_flex import recommendation_flex

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
        if isinstance(entry['text'],dict):
            push_message(user,entry['text'],entry['retry_key'])
        else:
            push(user,entry['text'],entry['retry_key'])
        entry['sent']=True;remaining-=1;put(key,state)
    return remaining

def run(slot,dry_run=True,now=None,catch_up=False):
    now=(now or local_now()).astimezone(TAIPEI);today=now.date()
    if slot not in ('morning','evening'):raise ValueError('slot錯誤')
    if not dry_run:
        start=(11,30) if slot=='morning' else (19,30);minute=now.hour*60+now.minute
        end = (19*60+30 if slot=='morning' else 24*60) if catch_up else start[0]*60+start[1]+60
        if not start[0]*60+start[1]<=minute<end:
            return {'status': 'outside_send_window', 'date': str(today), 'slot': slot}
    init_db()
    if not is_session(today):return {'status':'closed','date':str(today)}
    with leased('recommendations:worker',seconds=840) as acquired:
        if not acquired:raise RuntimeError('另一排名工作執行中')
        deadline=time.monotonic()+600
        from app.day_trader.reporting import preferences as four_preferences, refresh_cached, summary as four_summary
        members=[u for u in member_users() if can_use_personal(u)]
        users=[u for u in members if preferences(u)['enabled']]
        four_users=[u for u in members if four_preferences(u).get('enabled')]
        if not users and not four_users:return {'status':'no_subscribers'}
        if not dry_run:
            def completed(prefix, user):
                state = get(f'{prefix}:outbox:{today}:{slot}:{user}') or {}
                return bool(state.get('messages')) and all(m.get('sent') for m in state['messages'])
            users = [u for u in users if not completed('recommendations', u)]
            four_users = [u for u in four_users if not completed('four_rankings', u)]
            if not users and not four_users:return {'status':'already_sent','date':str(today),'slot':slot}
        target=target_day(today,slot)
        remaining=0 if dry_run else quota()
        initial_remaining=remaining
        four_reports=0
        for user in four_users:
            if time.monotonic()>deadline:raise TimeoutError('排名工作超過時間預算')
            four_key=f'four_rankings:outbox:{today}:{slot}:{user}'
            if get(four_key) and not dry_run:
                remaining=deliver(user,four_key,[],False,remaining)
                continue
            four_report=refresh_cached(user,str(target))
            if any(four_report['rankings'].values()):
                four_text=four_summary(four_report)
                if four_text:
                    remaining=deliver(user,four_key,[four_text],dry_run,remaining)
                    four_reports+=1
        if not users:
            return {'status':'preview' if dry_run else 'sent','reports':[], 'four_reports':four_reports,'messages_sent':initial_remaining-remaining}
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
        reports=[]
        for user in users:
            if time.monotonic()>deadline:raise TimeoutError('排名工作超過時間預算')
            key=f'recommendations:outbox:{today}:{slot}:{user}';pending=get(key)
            if pending and not dry_run:
                remaining=deliver(user,key,[],False,remaining);continue
            items,coverage=collect(symbols,snapshots,target,user,deadline)
            report={**rank(items,settings_for(user),today),'coverage':coverage,'target_date':str(target),'date':str(today),'slot':slot,'slot_label':'11:30' if slot=='morning' else '19:30','universe_partial':partial,'generated_at':now.isoformat()}
            texts=messages(report)
            # Summary stays a plain text message; ranked stocks become one
            # Flex carousel only when the configured public URL is valid.
            flex_items=[{'symbol':d['symbol'],'name':d.get('name'),
                         'score':d['rating'].get('score'),
                         'relaxation_round':d.get('relaxation_round',0)}
                        for d in report['items']]
            flex=recommendation_flex(flex_items,settings.public_app_url)
            if flex is not None:
                texts=[texts[0],flex]
            put('recommendations:'+('preview:' if dry_run else 'latest:')+user,report)
            remaining=deliver(user,key,texts,dry_run,remaining)
            reports.append({'matched':report['matched'],'round':report['round'],'coverage':coverage,'messages':len(texts)})
        return {'status':'preview' if dry_run else 'sent','reports':reports,'four_reports':four_reports}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--slot',choices=['morning','evening','auto'],required=True);p.add_argument('--send',action='store_true');a=p.parse_args()
    now=local_now()
    if a.slot=='auto':
        slot='evening' if (now.hour,now.minute)>=(19,30) else 'morning'
        print(run(slot,dry_run=not a.send,now=now,catch_up=True))
    else:
        print(run(a.slot,dry_run=not a.send,now=now))
