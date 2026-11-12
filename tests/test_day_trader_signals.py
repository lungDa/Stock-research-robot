from datetime import datetime, timedelta, timezone
import pytest
from app.day_trader.signals import Bar, analyze

def bars():
    start=datetime(2026,11,10,1,tzinfo=timezone.utc)
    return [Bar(start+timedelta(minutes=i*5),100,101,99,100,1000) for i in range(20)]

def test_breakout_is_research_only():
    b=bars()
    b.append(Bar(b[-1].timestamp+timedelta(minutes=5),101,105,100,104,2000))
    result=analyze("2330.TW",b)
    assert result["signal"]=="BREAKOUT_WATCH"
    assert result["tradable"] is False
    assert result["stop_reference"]==99

def test_no_signal_and_missing_data():
    b=bars()
    assert analyze("2330.TW",b)["signal"]=="INSUFFICIENT_DATA"
    b.append(Bar(b[-1].timestamp+timedelta(minutes=5),100,101,99,100,1000))
    assert analyze("2330.TW",b)["signal"]=="NO_SIGNAL"

def test_invalid_bars_rejected():
    b=bars()
    b.append(Bar(b[-1].timestamp,100,101,99,100,1000))
    with pytest.raises(ValueError): analyze("2330.TW",b)
