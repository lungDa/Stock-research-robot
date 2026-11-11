from datetime import datetime,timedelta,timezone
import pytest
from app.day_trader.hybrid_data import FeedResult, MarketDataUnavailable, choose_feed, readiness

NOW=datetime(2026,11,11,1,tzinfo=timezone.utc)

def test_free_history_and_fundamentals():
    f=FeedResult("TWSE",NOW-timedelta(days=30),{"eps":5},True)
    assert choose_feed(purpose="fundamentals",free_feed=f,now=NOW).source=="TWSE"
    assert choose_feed(purpose="history",free_feed=f,now=NOW).source=="TWSE"

def test_intraday_requires_authorized_fresh_yuanta():
    free=FeedResult("free",NOW,{"close":100},True)
    with pytest.raises(MarketDataUnavailable):
        choose_feed(purpose="intraday",free_feed=free,now=NOW)
    stale=FeedResult("YUANTA_SPARK",NOW-timedelta(minutes=6),{"close":100},True)
    with pytest.raises(MarketDataUnavailable):
        choose_feed(purpose="intraday",yuanta_feed=stale,now=NOW)
    unlicensed=FeedResult("YUANTA_SPARK",NOW,{"close":100},True,False)
    with pytest.raises(MarketDataUnavailable):
        choose_feed(purpose="intraday",yuanta_feed=unlicensed,now=NOW)
    valid=FeedResult("YUANTA_SPARK",NOW-timedelta(seconds=30),{"close":100},True,True)
    assert choose_feed(purpose="intraday",yuanta_feed=valid,now=NOW)==valid

def test_readiness_fails_closed():
    assert readiness(now=NOW)["feeds"]["intraday"]["ready"] is False
    assert readiness(now=NOW)["live_orders_enabled"] is False
