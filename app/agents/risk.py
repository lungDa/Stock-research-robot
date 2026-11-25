"""Long-only TWD snapshot risk; no execution, network or persistence."""
from datetime import datetime
from math import isfinite,sqrt
from copy import deepcopy
import hashlib,json
import pandas as pd
from app.agents.research import ResearchAgent
from app.services.defensive_model import risk_level,RiskRule,BENCHMARK_WEIGHTS
from app.services.freshness import TAIPEI

def num(x):
    return type(x) in (float,int) and isfinite(x)

def metrics(r):
    if len(r)<60:return None
    losses=-r
    var=max(0.,float(losses.quantile(.95)))
    # Expected shortfall: mean of worst ceil(5%) observations.
    from math import ceil
    es=max(0.,float(losses.nlargest(ceil(len(r)*.05)).mean()))
    wealth=pd.concat([pd.Series([1.]),(1+r).cumprod().reset_index(drop=True)],ignore_index=True)
    return {"samples":len(r),"annual_volatility":float(r.std()*sqrt(252)),
            "max_drawdown":float((1-wealth/wealth.cummax()).max()),
            "var95_daily":var,"cvar95_daily":max(var,es)}

class RiskAgent:
    def analyze(self, *, positions, now, cash=0, limits=None):
        if not isinstance(now,datetime) or now.utcoffset() is None or not isinstance(positions,list) or not 1<=len(positions)<=20 or not num(cash) or cash<0:
            raise ValueError("invalid portfolio")
        now=now.astimezone(TAIPEI)
        positions,limits=deepcopy((positions,limits))
        limits={"single":.25,"sector":.40,"equity":.90} if limits is None else limits
        if set(limits)!={"single","sector","equity"} or any(not num(v) or not 0<v<=1 for v in limits.values()):raise ValueError("limits")
        values={}; sectors={}; reports={}; series={}
        for p in positions:
            x=p["research"]
            symbol=x["symbol"]
            if symbol in values or p.get("currency")!="TWD" or not num(p.get("quantity")) or not 0<p["quantity"]<=1e9:raise ValueError("position")
            r=ResearchAgent().analyze(now=now,**x)
            q=x["quote"]
            if r["component_confidence"]["market"]!=100 or not num(q["price"]) or not 0<q["price"]<=1e7:raise ValueError("market")
            values[symbol]=p["quantity"]*q["price"]
            sector=p.get("sector","unknown")
            if not isinstance(sector,str) or not 1<=len(sector)<=64:raise ValueError("sector")
            sectors[symbol]=sector
            reports[symbol]={"research_version":r["evidence_version"],"confidence":r["confidence"],"financial_audit":r["financial_audit"],"downside_beta":r["defensive"].get("downside_beta")}
            if r["technical"]["complete"]:
                bars=x["bars"]
                s=pd.Series([b["close"] for b in bars],index=[b["date"] for b in bars],dtype=float)
                ret=s.pct_change().dropna()
                if len(ret)>=60 and all(isfinite(v) and v>-1 for v in ret):
                    series[symbol]=ret
                    reports[symbol]["metrics"]=metrics(ret)
        total=sum(values.values())+cash
        if not isfinite(total) or total<=0:raise ValueError("total")
        weights={k:v/total for k,v in values.items()}
        sector_weights={}
        for k,w in weights.items():sector_weights[sectors[k]]=sector_weights.get(sectors[k],0)+w
        breaches=[{"type":"single","symbol":k} for k,w in weights.items() if w>limits["single"]]
        breaches += [{"type":"sector","sector":k} for k,w in sector_weights.items() if w>limits["sector"]]
        if sum(weights.values())>limits["equity"]:breaches.append({"type":"equity"})
        portfolio=None
        if len(series)==len(values):
            aligned=pd.concat(series,axis=1,join="inner")
            if len(aligned)>=60 and all(list(s.index)==list(aligned.index) for s in series.values()):
                portfolio=metrics(sum(aligned[k]*w for k,w in weights.items()))
        # Static shocks, not forecasts. No assumption of ETF constituent look-through.
        stress={str(shock):sum(weights.values())*shock for shock in (-.10,-.20,-.30)}
        digest=hashlib.sha256(json.dumps([positions,cash,limits,now.isoformat()],sort_keys=True,allow_nan=False).encode()).hexdigest()
        return {"mode":"shadow","status":"risk_only","execution_allowed":False,"verified":False,
                "evidence_version":digest,"as_of":now.isoformat(),"currency":"TWD","weights":weights,"cash_weight":cash/total,
                "sector_weights":sector_weights,"sector_scope":"caller_labels_no_lookthrough","limits":limits,"breaches":breaches,
                "positions":reports,"portfolio_metrics":portfolio,"stress_returns":stress,
                "risk_grade":"limit_breach" if breaches else "incomplete" if portfolio is None or "unknown" in sector_weights else "within_configured_limits",
                "scope":"constant_weight_historical_simulation_not_actual_portfolio_performance"}
