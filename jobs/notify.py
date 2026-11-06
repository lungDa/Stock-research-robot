"""每天每人一份；先預留額度，LINE retry key 防止不確定回應造成重複發送。"""
import logging,uuid,time
from datetime import datetime
from zoneinfo import ZoneInfo
from app.config import settings
from app.db import init_db,get,put,claim
from app.channels.line import quota,push
from app.services.watchlist import subscribed,watches
from app.services.freshness import format_updated_at,quote_note
log=logging.getLogger(__name__)
def run():
    deadline=time.monotonic()+40
    init_db()
    report=get('scan:latest',{})
    if not report: raise RuntimeError('尚無掃描結果，不送空報告')
    from datetime import timezone
    if (datetime.now(timezone.utc)-datetime.fromisoformat(report['updated_at'])).total_seconds()>36*3600:
        raise RuntimeError('掃描報告過期，不發送')
    day=datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat()
    remaining=quota()
    for user in subscribed():
        if time.monotonic()>deadline-8:
            log.warning("通知達時間預算，剩餘名單保留待下次執行")
            break
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
        lines=[f'股海燈塔 {day}',f"掃描涵蓋 {report.get('fresh_count',0)}/{report.get('universe_size',0)} 檔（本次批次，非全市場）",'存股：'+('、'.join(report.get('income',[])[:3]) or '無符合'),
               '波段：'+('、'.join(report.get('swing',[])[:3]) or '無符合'),f"實際行情日：{'、'.join(sorted(report.get('data_dates',[]))) or '請依各標的日期'}",
               f"今日行情 {report.get('today_count',0)} 檔；更新 {format_updated_at(report.get('updated_at'))}",'你的追蹤：']
        for symbol in watches(user):
            d=get('quote:'+symbol)
            lines.append(f"{symbol}｜{d['price']:.2f}｜行情日 {d['date']}"+('（非今日行情）' if d['date']!=day else '') if d else symbol+'｜尚無資料')
        lines.append('個股與ETF規則不同；詳情請開網頁。')
        try:
            push(user,'\n'.join(lines),retry_key)
            put(key,{'status':'sent','retry_key':retry_key})
        except Exception:
            # 自動重試只允許同一天且沿用相同 key；額度保守計算。
            log.warning('通知暫未完成，已保留同一retry key待重試')
            put(key,{'status':'retry','retry_key':retry_key})
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO);run()
