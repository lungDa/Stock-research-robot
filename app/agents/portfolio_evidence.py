"""Bounded, one-level portfolio evidence; no external I/O."""
from datetime import date,timedelta
from math import isfinite
from app.agents.audit_policy import origin
from app.agents.research_evidence import timestamp,technical_evidence
from app.services.trading_calendar import session
from app.services.v26_coverage_adapter import CODE

def num(v):
    return type(v) in (int,float) and isfinite(v)

def continuous_sessions(days,documents):
    try:
        ds=[date.fromisoformat(d) for d in days]
        if not ds or (ds[-1]-ds[0]).days>2000:return False
        expected=[ds[0]+timedelta(days=i) for i in range((ds[-1]-ds[0]).days+1)]
        states=[session(d,documents.get) for d in expected]
        return None not in states and [d for d,v in zip(expected,states) if v]==ds
    except (TypeError,ValueError):return False

def holdings(p,now):
    d=p.get("holdings")
    if not isinstance(d,dict):return None
    at=timestamp(d.get("observed_at"))
    try:day=date.fromisoformat(d["as_of"])
    except (ValueError,TypeError,KeyError):return None
    if d.get("symbol")!=p["research"]["symbol"] or d.get("basis")!="net_asset_weight" or origin(d.get("source_url")) not in ("twse.com.tw","tpex.org.tw") or at is None or not day<=at.date()<=now.date() or not 0<=(now-at).total_seconds()<=8*86400 or not 0<=(now.date()-day).days<=8:return None
    rows=d.get("rows")
    if not isinstance(rows,list) or not 1<=len(rows)<=500:return None
    seen=set()
    for r in rows:
        if not isinstance(r,dict) or not isinstance(r.get("symbol"),str) or not CODE.fullmatch(r["symbol"]) or r.get("kind")!="STOCK" or r["symbol"] in seen or not num(r.get("weight")) or not 0<r["weight"]<=1:return None
        seen.add(r["symbol"])
    if sum(r["weight"] for r in rows)>1+1e-10:return None
    return rows

def exposures(positions,weights,sectors,now):
    underlying={}; groups={}; contributors={}; unknown=0.
    def add(symbol,weight,sector,via):
        underlying[symbol]=underlying.get(symbol,0.)+weight
        contributors.setdefault(symbol,[]).append(via)
        groups[sector]=groups.get(sector,0.)+weight
    for p in positions:
        x=p["research"]; k=x["symbol"]; w=weights[k]
        if x["quote"]["kind"]=="STOCK":add(k,w,sectors[k],k);continue
        rows=holdings(p,now)
        if rows is None:unknown+=w;continue
        for r in rows:
            # Reuse direct verified sector evidence; constituent labels alone are not proof.
            add(r["symbol"],w*r["weight"],sectors.get(r["symbol"],"unknown"),k)
        unknown+=w*max(0.,1-sum(r["weight"] for r in rows))
    if unknown>1e-10:groups["unknown"]=groups.get("unknown",0.)+unknown
    return {"underlying":underlying,"sectors":groups,"unknown_weight":unknown,"overlaps":{k:v for k,v in contributors.items() if len(v)>1},"scope":"one_level_long_only_snapshot","verified":False}

def liquidity(p,value,now):
    x=p["research"]; bars=x.get("bars"); q=x["quote"]
    missing={"status":"insufficient_data"}
    if not technical_evidence(bars,q,now,x["documents"],True)["complete"]:return missing
    # Explicit raw traded shares, not adjusted volume or lot counts.
    recent=bars[-20:]
    if any(b.get("volume_unit")!="shares" or not num(b.get("raw_volume")) or b["raw_volume"]<0 or not num(b.get("raw_close")) or b["raw_close"]<=0 for b in recent):return missing
    adv=sum(b["raw_volume"]*b["raw_close"] for b in recent)/20
    if not isfinite(adv) or adv<=0:return missing
    return {"status":"available","average_daily_value_twd":adv,"days_at_10pct_adv":value/(.1*adv),"samples":20,"scope":"illustrative_no_market_impact"}
