"""Conservative per-symbol AI research cache decision.

Do not cache a report if source data is stale/incomplete; never treat cached
commentary as current quotes. Storage/invocation wiring is intentionally separate.
"""
from datetime import datetime, timezone, timedelta
from math import isfinite

def _timestamp(value):
    if isinstance(value,str):
        try:value=datetime.fromisoformat(value.replace("Z","+00:00"))
        except ValueError:return None
    if not isinstance(value,datetime) or value.tzinfo is None:return None
    return value.astimezone(timezone.utc)

def _score(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and isfinite(value) and 0<=value<=100

def decide_cache(current, cached, *, now=None, max_age_hours=24, score_delta=5):
    """Return explicit refresh/reuse decision; cache is not an order signal."""
    now=_timestamp(now or datetime.now(timezone.utc))
    if now is None or max_age_hours<=0 or score_delta<=0:
        raise ValueError("invalid cache configuration")
    if not isinstance(current,dict) or not current.get("symbol"):
        raise ValueError("current symbol required")
    if current.get("data_stale") is True or current.get("data_complete") is not True:
        return {"action":"SKIP","reason":"資料過期或不完整"}
    if not all(_score(current.get(k)) for k in ("fundamental_score","technical_score")):
        return {"action":"SKIP","reason":"量化評分缺漏"}
    if not isinstance(cached,dict) or cached.get("symbol")!=current["symbol"]:
        return {"action":"REFRESH","reason":"無有效同股快取"}
    generated=_timestamp(cached.get("generated_at"))
    if generated is None or generated>now or now-generated>timedelta(hours=max_age_hours):
        return {"action":"REFRESH","reason":"快取超過有效期限"}
    if cached.get("ai_status")!="OK" or not cached.get("commentary"):
        return {"action":"REFRESH","reason":"既有AI報告無效"}
    if cached.get("signal")!=current.get("signal"):
        return {"action":"REFRESH","reason":"交易研究訊號變動"}
    if cached.get("source_revision")!=current.get("source_revision"):
        return {"action":"REFRESH","reason":"資料版本變動"}
    for key in ("fundamental_score","technical_score"):
        if not _score(cached.get(key)):
            return {"action":"REFRESH","reason":"快取評分無效"}
        if abs(current[key]-cached[key])>=score_delta:
            return {"action":"REFRESH","reason":key+"變化達門檻"}
    return {"action":"REUSE","reason":"評分與訊號穩定","original_generated_at":generated.isoformat(),
            "display_notice":"沿用先前AI解讀；最新量化評分另行顯示"}
