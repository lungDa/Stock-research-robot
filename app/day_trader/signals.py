"""Research-only Taiwan signal analysis.

Adapted conceptually from Jakeschincariol/day-trader-skill (MIT).
Uses *completed* OHLCV bars supplied by the caller; no external calls.
Never places orders or changes positions.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite

@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

def analyze(symbol: str, bars: list[Bar], *, max_risk_pct: float = 0.01) -> dict:
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol required")
    if not 0 < max_risk_pct <= 0.05:
        raise ValueError("max_risk_pct must be between 0 and 0.05")
    if len(bars) < 21:
        return {"symbol":symbol, "signal":"INSUFFICIENT_DATA", "tradable":False,
                "reason":"至少需要21根已收盤K棒"}
    last_time=None
    for b in bars:
        values=(b.open,b.high,b.low,b.close,b.volume)
        if (b.timestamp.tzinfo is None or (last_time is not None and b.timestamp <= last_time)
            or any(not isfinite(v) for v in values) or min(b.open,b.high,b.low,b.close)<=0
            or b.volume<0 or b.low>min(b.open,b.close) or b.high<max(b.open,b.close)):
            raise ValueError("invalid, unordered, or non-completed OHLCV bars")
        last_time=b.timestamp
    latest=bars[-1]
    prev=bars[-21:-1]
    resistance=max(b.high for b in prev)
    support=min(b.low for b in prev)
    avg_volume=sum(b.volume for b in prev)/len(prev)
    if avg_volume<=0:
        return {"symbol":symbol,"signal":"INSUFFICIENT_DATA","tradable":False,
                "reason":"歷史成交量不足"}
    breakout=latest.close>resistance and latest.volume>=1.5*avg_volume
    breakdown=latest.close<support and latest.volume>=1.5*avg_volume
    if breakout:
        stop=support
        risk=latest.close-stop
        signal="BREAKOUT_WATCH"
    elif breakdown:
        stop=resistance
        risk=stop-latest.close
        signal="BREAKDOWN_WATCH"
    else:
        stop=None
        risk=None
        signal="NO_SIGNAL"
    return {"symbol":symbol,"signal":signal,"tradable":False,
            "reference_close":latest.close,"resistance":resistance,"support":support,
            "relative_volume":round(latest.volume/avg_volume,3),
            "stop_reference":stop,"risk_per_share":risk,
            "risk_budget_fraction":max_risk_pct,
            "reason":"研究訊號，未經交易日曆、成交量品質、成本、回測與風控審核"}
