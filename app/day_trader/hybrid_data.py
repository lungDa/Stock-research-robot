"""Fail-closed hybrid research data routing.

Free/official sources: fundamentals and historical bars.
Yuanta SPARK: licensed intraday bars, only after explicit entitlement checks.
No credentials, network calls, or broker execution are implemented here.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class FeedResult:
    source: str
    as_of: datetime
    payload: object
    complete: bool
    authorized: bool = True

class MarketDataUnavailable(ValueError):
    pass

def choose_feed(*, purpose, free_feed=None, yuanta_feed=None, now=None, max_age_seconds=300):
    if purpose not in ("fundamentals","history","intraday"):
        raise ValueError("unknown data purpose")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("now must be timezone aware")
    if max_age_seconds<=0:raise ValueError("invalid freshness threshold")
    # Do not use unlicensed intraday data or silently fall back to stale free quotes.
    feeds=(yuanta_feed,) if purpose=="intraday" else (free_feed,)
    for feed in feeds:
        if not isinstance(feed,FeedResult) or not feed.complete or not feed.authorized:
            continue
        if feed.as_of.tzinfo is None or feed.as_of>now:
            continue
        if purpose=="intraday" and (now-feed.as_of).total_seconds()>max_age_seconds:
            continue
        if feed.payload is None:
            continue
        return feed
    raise MarketDataUnavailable("行情未授權、缺漏或逾時；停止該類研究排名")

def readiness(*, free_fundamentals=None, free_history=None, yuanta_intraday=None, now=None):
    output={}
    for purpose,feed in (("fundamentals",free_fundamentals),("history",free_history),
                         ("intraday",yuanta_intraday)):
        try:
            choose_feed(purpose=purpose,free_feed=feed,yuanta_feed=feed,now=now)
            output[purpose]={"ready":True,"source":feed.source}
        except MarketDataUnavailable as exc:
            output[purpose]={"ready":False,"reason":str(exc)}
    return {"feeds":output,"live_orders_enabled":False,"mode":"RESEARCH_ONLY"}
