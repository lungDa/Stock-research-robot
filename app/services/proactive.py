"""少量盤後主動關懷。沿用單檔通知槽位，不自行擴大額度。"""
import time,uuid,requests
from app.db import get,put
from app.services import assistant
from app.services.watchlist import watches


def nudge(user,day,now,remaining,cap,reserve,push,deadline,local):
    if local.weekday()>=5 or (local.hour,local.minute)<(18,17):return remaining
    prefs=assistant.preferences(user);tracked=watches(user)
    kind='brief' if tracked else 'empty'
    enabled=prefs['daily_brief'] if tracked else prefs['empty_reminder']
    if not enabled:return remaining
    key='assistant:delivery:'+day+':'+user
    state=get(key,{})
    if state.get('status') in ('sent','expired','blocked'):return remaining
    pending=state.get('pending')
    if not pending:
        if tracked:
            # 同日任何單檔訊號已送達，就不另外補摘要。
            if any(get('signal:state:'+user+':'+s,{}).get('pending') for s in tracked):return remaining
            if any(get('signal:state:'+user+':'+s,{}).get('sent_at',0)>=local.replace(hour=0,minute=0,second=0,microsecond=0).timestamp() for s in tracked):return remaining
            report=get('scan:latest',{})
            if not report.get('updated_at'):return remaining
            from datetime import datetime
            try:age=now-datetime.fromisoformat(report['updated_at']).timestamp()
            except (ValueError,TypeError):return remaining
            if not 0<=age<=36*3600:return remaining
        elif now-get('assistant:empty:last:'+user,{}).get('at',0)<7*86400:return remaining
        if time.monotonic()>deadline-20:return remaining
        if remaining is None:
            from app.channels.line import quota
            remaining=quota()
        if remaining<=5 or not reserve(user,day,cap):return remaining
        content=('盤後助理｜'+day+'\n'+assistant.summary(user)+'\n可說「我的分級」「通知設定」。' if tracked else
                 '股海燈塔提醒：你尚未設定追蹤。可直接說「幫我追蹤台積電」或「追蹤00878」；再到個人設定調整需求。\n此提醒最多7天一次，可用「只看重要訊號」關閉。')
        pending={'created_at':now,'retry_key':str(uuid.uuid4()),'text':content,'last_attempt':0,'kind':kind}
        put(key,{'pending':pending})
        if kind=='empty':put('assistant:empty:last:'+user,{'at':now,'status':'reserved'})
    elif now-pending['created_at']>23*3600:
        put(key,{'status':'expired','uncertain_delivery':True});return remaining
    elif now-pending.get('last_attempt',0)<60:return remaining
    if time.monotonic()>deadline-20:return remaining
    if remaining is None:
        from app.channels.line import quota
        remaining=quota()
    if remaining<=5:return remaining
    pending['last_attempt']=time.time();put(key,{'pending':pending});remaining-=1
    try:
        push(user,pending['text'],pending['retry_key'])
        put(key,{'status':'sent','at':time.time()})
        if pending['kind']=='empty':put('assistant:empty:last:'+user,{'at':now})
    except Exception as exc:
        if isinstance(exc,requests.HTTPError) and exc.response is not None and 400<=exc.response.status_code<500:put(key,{'status':'blocked'})
    return remaining
