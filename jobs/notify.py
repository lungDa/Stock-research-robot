"""追蹤標的升降級才推播；每檔獨立訊息、每日硬上限、不可變重試內容。"""
import logging,time,uuid
from datetime import datetime,timezone
import requests
from app.config import settings
from app.services.accounts import can_use_personal
from app.db import init_db,get,put,claim
from app.channels.line import quota,push
from app.services.watchlist import subscribed,watches
from app.services.research import cached_quote
from app.services.multifactor import settings_for,rated,config_hash
from app.services.freshness import local_now
from app.services.assistant import display_symbol
from app.services.proactive import nudge
log=logging.getLogger(__name__)
RANK={'資料不足':-1,'觀望':0,'買':1,'強力買':2}

def slot(user,day,cap):
    for i in range(cap):
        if claim(f'signal:slot:{day}:{user}:{i}',{'at':time.time()}):return True
    return False

def message(d,previous):
    r=d['rating']; missing=[x['label'] for x in r['checks'] if x['passed'] is None]
    return (f"股海燈塔｜{d['name']}（{display_symbol(d['symbol'])}）\n"
        f"{previous or '首次符合'} → {r['grade']}"+('（資料缺漏，非財務惡化判定）' if r['grade']=='資料不足' else '')+f"\n行情日 {d['date']}｜{d['currency']} {d['price']:.2f}\n"
        f"規則分數 {r['score'] if r['score'] is not None else '無'}｜完整度 {r['coverage']}%\n"
        +('缺資料：'+'、'.join(missing[:3])+'\n' if missing else '')
        +'詳細條件請看Streamlit。規則分級非報酬預測。')

def run():
    init_db();deadline=time.monotonic()+40; now=time.time();day=local_now().date().isoformat()
    remaining=None
    for user in subscribed():
        if not can_use_personal(user):continue
        c=settings_for(user);revision=config_hash(c)
        for symbol in watches(user)[:30]:
            if time.monotonic()>deadline-20:return
            key='signal:state:'+user+':'+symbol;state=get(key,{})
            pending=state.get('pending')
            if pending:
                # 不跨日或超過23小時重試，避免LINE去重期限過後重送。
                if pending['day']!=day or now-pending['created_at']>23*3600:
                    put(key,{'grade':pending['grade'],'config_hash':pending['config_hash'],'uncertain_delivery':True})
                    continue
                if pending.get('blocked') or now-pending.get('last_attempt',0)<60:continue
            else:
                d=cached_quote(symbol)
                if not d or now-d.get('cached_at',0)>36*3600 or d.get('data_status')=='stale':continue
                try:
                    if not 0<=(local_now().date()-datetime.fromisoformat(d['date']).date()).days<=7:continue
                except (KeyError,ValueError):continue
                d=rated(d,user);grade=d['rating']['grade'];previous=state.get('grade')
                # 儲存規則改變後建立新基準，不以規則修改冒充行情訊號。
                if state and state.get('config_hash')!=revision:
                    put(key,{'grade':grade,'config_hash':revision});continue
                changed=previous!=grade and (previous is not None or grade in ('買','強力買'))
                if not changed:
                    if not state:put(key,{'grade':grade,'config_hash':revision})
                    continue
                if c['notify_direction']=='up' and RANK[grade]<=RANK.get(previous,-1):
                    put(key,{'grade':grade,'config_hash':revision});continue
                if remaining is None:remaining=quota()
                if remaining<=5:return
                if not slot(user,day,c['daily_cap']):continue
                pending={'day':day,'created_at':now,'retry_key':str(uuid.uuid4()),
                         'grade':grade,'config_hash':revision,'text':message(d,previous),'last_attempt':0}
                state={**state,'pending':pending};put(key,state)
            if remaining is None:remaining=quota()
            if remaining<=5:return
            pending['last_attempt']=time.time();put(key,{**state,'pending':pending});remaining-=1
            try:
                push(user,pending['text'],pending['retry_key'])
                put(key,{'grade':pending['grade'],'config_hash':pending['config_hash'],'sent_at':time.time()})
            except Exception as exc:
                # 明確4xx（409由line.send處理）不盲目重試；網路不確定回應沿用同payload/key。
                if isinstance(exc,requests.HTTPError) and exc.response is not None and 400<=exc.response.status_code<500:
                    pending['blocked']=True
                    put(key,{**state,'pending':pending})
                log.warning('單檔通知未確認，保留狀態；不新增重複訊息')

        remaining=nudge(user,day,now,remaining,c['daily_cap'],slot,push,deadline,local_now())

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO);run()
