"""Snapshot validation and reuse of existing market risk policy."""
from datetime import time
from math import isfinite,isclose
import pandas as pd
from app.agents.audit_policy import origin
from app.agents.research_evidence import timestamp
from app.services.trading_calendar import session

def num(v):
    return type(v) in (int,float) and isfinite(v)

def valid_returns(r):
    return isinstance(r,pd.Series) and 60<=len(r)<=1500 and r.index.is_unique and r.index.is_monotonic_increasing and all(num(v) and -1<v<=10 for v in r)

def sector_evidence(p,symbol,now):
    e=p.get("sector_evidence",{})
    at=timestamp(e.get("observed_at"))
    sector=p.get("sector")
    if p["research"]["quote"]["kind"]=="ETF":return "unknown"
    if e.get("symbol")==symbol and e.get("sector")==sector and isinstance(sector,str) and 0<len(sector.strip())<=64 and origin(e.get("source_url")) in ("twse.com.tw","tpex.org.tw") and at is not None and 0<=(now-at).total_seconds()<=8*86400:return sector.strip()
    return "unknown"

def beta(ret,benchmark,now):
    if not valid_returns(ret) or not isinstance(benchmark,dict) or benchmark.get("id")!="TAIEX" or benchmark.get("basis")!="total_return":return None
    rows=benchmark.get("rows")
    if not isinstance(rows,list) or len(rows)!=len(ret):return None
    try:
        if [r["date"] for r in rows]!=list(ret.index):return None
        for r in rows:
            at=timestamp(r.get("observed_at"))
            if at is None or at>now or at.date().isoformat()!=r["date"] or at.time()<time(13,30) or origin(r.get("source_url"))!="twse.com.tw":return None
            a,b=r["previous"],r["close"]
            if not num(a) or not num(b) or min(a,b)<=0 or not num(r["return"]) or not isclose(b/a-1,r["return"],abs_tol=1e-9):return None
        if any(not isclose(a["close"],b["previous"],rel_tol=1e-9) for a,b in zip(rows,rows[1:])):return None
        s=pd.Series([r["return"] for r in rows],index=ret.index)
        if not valid_returns(s) or s.nunique()<2 or s.var()<=1e-12:return None
        v=ret.cov(s)/s.var()
        return float(v) if isfinite(v) else None
    except (KeyError,TypeError,ValueError):return None

