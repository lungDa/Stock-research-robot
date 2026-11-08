"""行情日期與更新時間分開；平日晚間排程不保證上游已公布當日資料。"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
TAIPEI = ZoneInfo('Asia/Taipei')


def local_now(): return datetime.now(TAIPEI)


def needs_evening_refresh(cached_at, quote_date, now=None):
    now = (now or local_now()).astimezone(TAIPEI)
    cutoff = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now.weekday() >= 5 or now < cutoff:
        return False
    return float(cached_at or 0) < cutoff.timestamp() and str(quote_date or '') < now.date().isoformat()


def format_updated_at(value):
    if not value: return '未記錄'
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(TAIPEI).strftime('%Y/%m/%d %H:%M（台灣）')
    except (TypeError, ValueError): return '未記錄'


def quote_note(data, now=None):
    if data.get('data_status')=='fundamentals_only':return '僅年度財報；尚無可用行情日期。'
    now = (now or local_now()).astimezone(TAIPEI)
    day = str(data.get('date', ''))
    if not data.get('symbol','').endswith(('.TW','.TWO')):
        return '各市場以實際行情日期為準。'
    if day == now.date().isoformat(): return '今日盤後行情。'
    if day > now.date().isoformat(): return '行情日期異常，請核對來源。'
    if now.weekday() < 5 and (now.hour, now.minute) < (18, 17):
        return '尚非今日行情；平日18:17啟動盤後更新，休市日保留最近交易日。'
    return '尚未取得今日行情：可能休市、停牌、來源未更新或本批未涵蓋；保留實際行情日。'
