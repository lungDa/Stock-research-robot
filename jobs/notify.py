"""每天每人一份；先預留額度，LINE retry key 防止不確定回應造成重複發送。"""
import logging,uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from app.config import settings
from app.db import init_db,get,put,claim
from app.channels.line import quota,push
from app.services.watchlist import subscribed,watches
log=logging.getLogger(__name__)
def run():
    init_db()
    report=get('scan:latest',{})
    if not report: raise RuntimeError('尚無掃描結果，不送空報告')
    from datetime import timezone
    if (datetime.now(timezone.utc)-datetime.fromisoformat(report['updated_at'])).total_seconds()>36*3600:
        raise RuntimeError('掃描報告過期，不發送')
    day=datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat()
    remaining=quota()
    for user in subscribed():
        if user not in settings.users.values(): continue
        key=f'notification:{day}:{user}'
        state=get(key)
        if state and state.get('status') in ('sent','reserved'): continue
        if remaining<=5: break  # 保留少量額度供其他用途；無額度不嘗試推播
        retry_key=str(uuid.uuid5(uuid.NAMESPACE_URL,key))
        # 保留未確認請求的額度，避免逾時後錯算剩餘額度。
        if state is None and not claim(key,{'status':'reserved','retry_key':retry_key}): continue
        if state is not None: put(key,{'status':'reserved','retry_key':retry_key})
        remaining-=1
        lines=[f'股海燈塔 {day}',f"掃描涵蓋 {report.get('fresh_count',0)}/{report.get('universe_size',0)} 檔（36小時內更新）",'存股：'+('、'.join(report.get('income',[])[:3]) or '無符合'),
               '波段：'+('、'.join(report.get('swing',[])[:3]) or '無符合'),'你的追蹤：']
        for symbol in watches(user):
            d=get('quote:'+symbol)
            lines.append(f"{symbol}｜{d['price']:.2f}｜{d['date']}" if d else symbol+'｜尚無資料')
        lines.append('個股與ETF規則不同；詳情請開網頁。')
        try:
            push(user,'\n'.join(lines),retry_key)
            put(key,{'status':'sent','retry_key':retry_key})
        except Exception:
            # 自動重試只允許同一天且沿用相同 key；額度保守計算。
            log.exception('notification failed')
            put(key,{'status':'retry','retry_key':retry_key})
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO);run()
