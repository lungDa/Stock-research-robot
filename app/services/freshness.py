"""行情日期與更新時間分開；平日晚間排程不保證上游已公布當日資料。"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math
import time
TAIPEI = ZoneInfo('Asia/Taipei')


def local_now(): return datetime.now(TAIPEI)


def market_usable(data, today=None):
    """One rule for web, LINE, scans and notifications; never refresh timestamps."""
    today = today or local_now().date()
    if data.get('data_status') in ('stale', 'fundamentals_only'):
        return False
    price = data.get('price')
    if type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
        return False
    try:
        day = datetime.fromisoformat(data['date']).date()
        return 0 <= (today-day).days <= 7
    except (KeyError, ValueError, TypeError):
        return False


def quote_due(data, now=None):
    if not data:
        return True
    now = time.time() if now is None else now
    ttl = 1800 if data.get('price_basis') == '未還原收盤價' else (300 if data.get('data_status') == 'partial' else 3600)
    if data.get('symbol', '').endswith(('.TW', '.TWO')) and needs_evening_refresh(data.get('cached_at'), data.get('date')):
        return True
    return now-data.get('cached_at', 0) >= ttl or not market_usable(data)


def mark_cached(data):
    if not data:
        return data
    if time.time()-data.get('cached_at', 0) > 36*3600 or not market_usable(data):
        return {**data, 'data_status': 'fundamentals_only' if data.get('price') is None else 'stale',
                'warnings': list(dict.fromkeys(data.get('warnings', [])+['目前顯示較舊或不完整行情；請核對行情日。']))}
    return data


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
    if data.get('data_status')=='stale':return '來源更新未確認，目前為舊快取；請核對行情日與更新時間。'
    now = (now or local_now()).astimezone(TAIPEI)
    day = str(data.get('date', ''))
    if not data.get('symbol','').endswith(('.TW','.TWO')):
        return '各市場以實際行情日期為準。'
    if day == now.date().isoformat(): return '今日盤後行情。'
    if day > now.date().isoformat(): return '行情日期異常，請核對來源。'
    if now.weekday() < 5 and (now.hour, now.minute) < (18, 17):
        return '尚非今日行情；平日18:17啟動盤後更新，休市日保留最近交易日。'
    return '尚未取得今日行情：可能休市、停牌、來源未更新或本批未涵蓋；保留實際行情日。'
