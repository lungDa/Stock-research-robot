"""Long-only TWD snapshot risk; no execution, network or persistence."""
from datetime import datetime,date,time,timedelta
from math import isfinite,sqrt,isclose
from copy import deepcopy
import hashlib,json
import pandas as pd
from app.agents.research import ResearchAgent
from app.agents.research_evidence import timestamp
from app.agents.audit_policy import origin
from app.services.trading_calendar import session
from app.services.defensive_model import risk_level,BENCHMARK_WEIGHTS,single_benchmark_levels
from app.services.freshness import TAIPEI
from app.agents.risk_evidence import valid_returns,sector_evidence,beta as taiex_beta
from jobs.monitor_defensive_risk import DEFAULT_RULES
from app.agents.portfolio_evidence import exposures, liquidity, continuous_sessions

def num(x):
    return type(x) in (float,int) and isfinite(x)

def metrics(r):
    if not valid_returns(r):return None
    losses=-r
    var=max(0.,float(losses.quantile(.95)))
    # Expected shortfall: mean of worst ceil(5%) observations.
    from math import ceil
    es=max(0.,float(losses.nlargest(ceil(len(r)*.05)).mean()))
    wealth=pd.concat([pd.Series([1.]),(1+r).cumprod().reset_index(drop=True)],ignore_index=True)
    result={"samples":len(r),"annual_volatility":float(r.std()*sqrt(252)),
            "max_drawdown":float((1-wealth/wealth.cummax()).max()),
            "var95_daily":var,"cvar95_daily":max(var,es),"tail_samples":ceil(len(r)*.05)}
    return {**result,"tail_confidence":"limited" if len(r)<252 else "larger_sample_not_calibrated"} if all(isfinite(v) for v in result.values()) else None

class RiskAgent:
    def analyze(self, *, positions, now, cash=0, limits=None, benchmarks=None, taiex=None):
        if not isinstance(now,datetime) or now.utcoffset() is None or not isinstance(positions,list) or not 1<=len(positions)<=20 or not num(cash) or cash<0:
            raise ValueError("invalid portfolio")
        now=now.astimezone(TAIPEI)
        positions,limits,benchmarks,taiex=deepcopy((positions,limits,benchmarks,taiex))
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
            sectors[symbol]=sector_evidence(p,symbol,now)
            reports[symbol]={"research_version":r["evidence_version"],"confidence":r["confidence"],"financial_audit":r["financial_audit"],"downside_beta":r["defensive"].get("downside_beta")}
            reports[symbol]["warnings"]=[]
            audit=r["financial_audit"]
            if sectors[symbol]=="unknown":reports[symbol]["warnings"].append("sector_unconfirmed")
            if r["confidence"]<100:reports[symbol]["warnings"].append("research_coverage_insufficient")
            if audit and (audit["conflicts"] or audit["invalid"] or audit["stale_sources"]):reports[symbol]["warnings"].append("financial_evidence_issue")
            if audit and any(e["field"]=="eps" and e["value"]<0 and e["year"]==str(now.year-1) for e in r["annual_evidence"]):reports[symbol]["warnings"].append("negative_latest_annual_eps")
            if r["technical"]["complete"]:
                bars=x["bars"]
                s=pd.Series([b["close"] for b in bars],index=[b["date"] for b in bars],dtype=float)
                ret=s.pct_change().dropna()
                if metrics(ret) is not None:
                    series[symbol]=ret
                    reports[symbol]["metrics"]=metrics(ret)
        total=sum(values.values())+cash
        if not isfinite(total) or total<=0:raise ValueError("total")
        weights={k:v/total for k,v in values.items()}
        exposure=exposures(positions,weights,sectors,now)
        sector_weights=exposure["sectors"]
        for p in positions:
            k=p["research"]["symbol"]
            reports[k]["liquidity"]=liquidity(p,values[k],now)
        breaches=[{"type":"single","symbol":k} for k,w in weights.items() if w>limits["single"]]
        breaches += [{"type":"sector","sector":k} for k,w in sector_weights.items() if k!="unknown" and w>limits["sector"]]
        breaches += [{"type":"underlying","symbol":k} for k,w in exposure["underlying"].items() if w>limits["single"]]
        if sum(weights.values())>limits["equity"]:breaches.append({"type":"equity"})
        portfolio=None
        correlation=None
        beta={}
        market=market_snapshot(benchmarks,now,positions[0]['research']['documents'])
        benchmark=market.pop('series',None)
        for k,s in series.items():
            beta[k]=market_beta(s,benchmark)
            reports[k]['beta']=beta[k]
            reports[k]['taiex_beta']=taiex_beta(s,taiex,now)
        if len(series)==len(values):
            aligned=pd.concat(series,axis=1,join="inner")
            if len(aligned)>=60 and all(list(s.index)==list(aligned.index) for s in series.values()):
                combined=sum(aligned[k]*w for k,w in weights.items())
                portfolio=metrics(combined)
                if portfolio is not None:
                    portfolio["beta"]=market_beta(combined,benchmark)
                    portfolio["taiex_beta"]=taiex_beta(combined,taiex,now)
                correlation={k:{j:correlation_value(aligned[k],aligned[j]) for j in aligned} for k in aligned}
        # Static shocks, not forecasts. No assumption of ETF constituent look-through.
        stress={str(shock):sum(weights.values())*shock for shock in (-.10,-.20,-.30)}
        differentiated={str(shock):sum(weights[k]*max(-1,beta[k]*shock) for k in weights) for shock in (-.10,-.20,-.30)} if all(beta.get(k) is not None for k in weights) else None
        digest=hashlib.sha256(json.dumps([positions,cash,limits,benchmarks,taiex,now.isoformat()],sort_keys=True,allow_nan=False).encode()).hexdigest()
        return {"mode":"shadow","status":"risk_only","execution_allowed":False,"verified":False,
                "evidence_version":digest,"as_of":now.isoformat(),"currency":"TWD","weights":weights,"cash_weight":cash/total,
                "sector_weights":sector_weights,"sector_scope":"one_level_snapshot_lookthrough","exposure":exposure,"schema_version":2,"limits":limits,"breaches":breaches,
                "positions":reports,"portfolio_metrics":portfolio,"stress_returns":stress,"beta_stress_returns":differentiated,"correlation":correlation,"market_risk":market,
                "risk_grade":"limit_breach" if breaches else "incomplete" if portfolio is None or portfolio["samples"]<252 or exposure["unknown_weight"]>1e-8 or "unknown" in sector_weights or any(r["liquidity"]["status"]!="available" for r in reports.values()) or market["level"] is None or any(beta.get(k) is None or reports[k]["warnings"] for k in weights) else "within_configured_limits",
                "scope":"constant_weight_historical_simulation_not_actual_portfolio_performance"}

# Existing market monitoring thresholds, copied as immutable snapshot defaults.
RULES=tuple(DEFAULT_RULES)

def correlation_value(a,b):
    if a.nunique()<2 or b.nunique()<2:return None
    v=a.corr(b)
    return float(v) if isfinite(v) else None

def market_beta(a,b):
    if b is None or not a.index.equals(b.index) or len(a)<60 or b.nunique()<2:return None
    v=b.var()
    result=a.cov(b)/v if v>1e-15 else float("nan")
    return float(result) if isfinite(result) else None

def market_snapshot(data,now,documents):
    missing={"level":None,"status":"insufficient_data","beta_basis":"weighted_five_benchmark_proxy"}
    if not isinstance(data,dict) or set(data)!=set(BENCHMARK_WEIGHTS):return missing
    try:
        series={}
        for key,rows in data.items():
            if not isinstance(rows,list) or not 60<=len(rows)<=1000:return missing
            days=[]; values=[]; releases=set()
            for row in rows:
                d=date.fromisoformat(row["date"])
                at=timestamp(row.get("published_at"))
                close=datetime.combine(d,time(13,30),TAIPEI)
                opening=datetime.combine(d,time(9),TAIPEI)
                if row.get("benchmark_id")!=key or not origin(row.get("source_url")) or session(d,documents.get) is not True or at is None or at>now or at in releases:return missing
                if key in ("nasdaq_100","sox"):
                    if not opening-timedelta(days=7)<=at<opening:return missing
                elif not close<=at<close+timedelta(hours=10):return missing
                a,b=row.get("previous"),row.get("close")
                if not num(a) or not num(b) or a<=0 or b<=0 or not num(row.get("return")) or not isclose(b/a-1,row["return"],abs_tol=1e-8) or not -1<row["return"]<=10:return missing
                days.append(d.isoformat());values.append(row["return"]);releases.add(at)
            if days!=sorted(set(days)) or days[-1]!=now.date().isoformat() or not continuous_sessions(days,documents):return missing
            if any(not isclose(a["close"],b["previous"],rel_tol=1e-8) for a,b in zip(rows,rows[1:])):return missing
            series[key]=pd.Series(values,index=days,dtype=float)
        if not all(s.index.equals(next(iter(series.values())).index) for s in series.values()):return missing
        returns={k:float(s.iloc[-1]) for k,s in series.items()}
        return {"status":"available","level":risk_level(returns,RULES),"beta_basis":"weighted_five_benchmark_proxy","series":sum(s*BENCHMARK_WEIGHTS[k] for k,s in series.items()),"returns":returns,"benchmark_levels":single_benchmark_levels(returns,RULES)}
    except (ValueError,TypeError,KeyError,OverflowError):return missing
