"""Conservative snapshot evidence adapters. No network or database reads."""
from datetime import date,datetime,time,timedelta
from math import isfinite,isclose
from app.agents.audit_policy import origin
from app.services.freshness import TAIPEI
from app.services.defensive_model import BENCHMARK_WEIGHTS
from app.services.v26_coverage_adapter import PREFIXES,_record
from jobs.v26_six_factor_coverage import valid_record
from app.services.trading_calendar import session
from app.day_trader.technical import score
from app.services.defensive_model import downside_statistics
import pandas as pd

FIELDS=("eps","roe_pct","cash_yield_pct","cash_dividend_per_share","cash_dividends_paid","operating_cash_flow","capital_expenditure","revenue")
def num(v):
    return type(v) in (int,float) and isfinite(v)

def annual_evidence(symbol,rows,documents,now,audit=None):
    blocked={tuple(x) for k in ('conflicts','invalid') for x in (audit or {}).get(k,[])}
    clean={}
    evidence=[]
    for year,row in rows.items():
        if not isinstance(year,str) or not year.isdigit() or len(year)!=4 or not now.year-11<=int(year)<now.year:continue
        for field in FIELDS:
            if (field,year) in blocked or (field in ('operating_cash_flow','capital_expenditure') and ('fcf',year) in blocked):continue
            v=row.get(field)
            if not num(v):continue
            matches=[]
            conflict=False
            for prefix in PREFIXES:
                doc=documents.get(prefix+symbol,{})
                source=doc.get("rows",{}).get(year,{})
                r=_record(source,field,int(year))
                if not r or not origin(r["source_url"]) or r["period_end"]!=year+"-12-31":continue
                if field in ("eps","roe_pct","cash_yield_pct") and not valid_record(r,int(year),field):continue
                if field in ("cash_dividends_paid","cash_dividend_per_share") and source.get(field+"_basis") not in ("paid","annual_paid","paid_common_cash_dividends"):continue
                if field in ("capital_expenditure","cash_dividends_paid","cash_dividend_per_share","cash_yield_pct","revenue") and r["value"]<0:continue
                meta=source.get("field_sources",{}).get(field,{})
                published=timestamp(meta.get("published_at"))
                if published is None or published>now or published.date()<date(int(year),12,31):continue
                stamp=doc.get("at")
                if not num(stamp) or stamp<published.timestamp() or not 0<=now.timestamp()-stamp<=(30 if prefix=="annual:shared:" else 90)*86400:continue
                if r["value"]!=v:conflict=True
                else:matches.append((prefix,r,published,stamp))
            if conflict or not matches:continue
            prefix,r,published,stamp=matches[0]
            clean.setdefault(year,{})[field]=v
            evidence.append({"field":field,"year":year,"source":prefix,"origin":origin(r["source_url"]),"unit":r["unit"],"period_end":r["period_end"],"value":v,"published_at":published.isoformat(),"observed_at":stamp})
    # Require compatible units for cash-flow arithmetic and cross-year series.
    for field in FIELDS:
        if len({e["unit"] for e in evidence if e["field"]==field})>1:
            for row in clean.values():row.pop(field,None)
    for year,row in clean.items():
        units={e["unit"] for e in evidence if e["year"]==year and e["field"] in ("operating_cash_flow","capital_expenditure","cash_dividends_paid")}
        if len(units)>1:
            for field in ("operating_cash_flow","capital_expenditure","cash_dividends_paid"):row.pop(field,None)
    return clean,[e for e in evidence if e["field"] in clean.get(e["year"],{})]

def timestamp(v):
    try:
        d=datetime.fromisoformat(v)
        return d.astimezone(TAIPEI) if d.utcoffset() is not None else None
    except (TypeError,ValueError):return None

def technical_evidence(bars,quote,now,documents,market):
    missing={"complete":False,"score":None}
    if not market or quote.get("adjustment_status")!="verified" or not isinstance(bars,list) or not 60<=len(bars)<=1000:return missing
    try:
        days=[date.fromisoformat(b["date"]) for b in bars]
        if days!=sorted(set(days)) or days[-1].isoformat()!=quote["date"]:return missing
        if (days[-1]-days[0]).days>2000:return missing
        if any(b.get("symbol")!=quote["symbol"] or b.get("completed") is not True or b.get("adjustment_status")!="verified" for b in bars):return missing
        for b,d in zip(bars,days):
            at=timestamp(b.get("observed_at"))
            if not origin(b.get("source_url")) or at is None or not datetime.combine(d,time(13,30),TAIPEI)<=at<=now:return missing
        for b in bars:
            factor=b.get("adjustment_factor")
            if not num(factor) or factor<=0 or not origin(b.get("adjustment_source_url")):return missing
            if any(not num(b.get("raw_"+k)) or not num(b.get(k)) or not isclose(b["raw_"+k]*factor,b[k],rel_tol=1e-6) for k in ("close","high","low")):return missing
        expected=[days[0]+timedelta(days=i) for i in range((days[-1]-days[0]).days+1)]
        states=[session(d,documents.get) for d in expected]
        if None in states or [d for d,v in zip(expected,states) if v]!=days:return missing
        if not num(quote.get("adjusted_close")) or bars[-1]["close"]!=quote["adjusted_close"]:return missing
        result=score(bars)
        return {**result,"samples":len(bars)}
    except (ValueError,TypeError,KeyError):return missing

def downside(data,symbol,now,documents):
    missing={"status":"insufficient_data"}
    if not isinstance(data,dict) or data.get("symbol")!=symbol or data.get("adjustment_status")!="verified" or data.get("alignment")!="released_before_taiwan_open":return missing
    if data.get("benchmark_id") not in BENCHMARK_WEIGHTS:return missing
    try:
        pairs=data["pairs"]
        if not isinstance(pairs,list) or not 60<=len(pairs)<=1500:return missing
        days=[date.fromisoformat(p["date"]) for p in pairs]
        if days!=sorted(set(days)) or days[-1]>now.date() or (now.date()-days[-1]).days>7:return missing
        if any(session(d,documents.get) is not True for d in days):return missing
        if any(not num(p[k]) or p[k]<-1 for p in pairs for k in ("stock","benchmark")):return missing
        releases=set()
        for p,d in zip(pairs,days):
            release=timestamp(p.get("benchmark_published_at"))
            observed=timestamp(p.get("stock_observed_at"))
            opening=datetime.combine(d,time(9),TAIPEI)
            closing=datetime.combine(d,time(13,30),TAIPEI)
            if release is None or observed is None or not opening-timedelta(days=7)<=release<opening or not closing<=observed<=now:return missing
            if p.get("benchmark_id")!=data["benchmark_id"] or release in releases:return missing
            releases.add(release)
            for key in ("stock","benchmark"):
                a,b=p.get(key+"_previous"),p.get(key+"_close")
                if not num(a) or not num(b) or a<=0 or b<=0 or not isclose(b/a-1,p[key],abs_tol=1e-8):return missing
            if not origin(p.get("stock_source_url")) or not origin(p.get("benchmark_source_url")):return missing
        idx=pd.DatetimeIndex(days)
        r=downside_statistics(pd.Series([p["stock"] for p in pairs],index=idx),pd.Series([p["benchmark"] for p in pairs],index=idx),pd.Timestamp(now.date()),data.get("years",1),severe_drop=.02)
        if r["down_sessions"]<20:return {**r,"status":"insufficient_down_sessions"}
        return r
    except (ValueError,TypeError,KeyError):return missing

def valuation(data,quote,now,market):
    pe=quote.get("pe")
    result={"pe":pe if market and num(pe) and pe>0 else None,"scope":"reported_multiple_not_fair_value"}
    if not market or not isinstance(data,dict) or data.get("symbol")!=quote["symbol"]:return result
    eps=data.get("eps")
    multiples=data.get("multiples")
    if not num(eps) or eps<=0 or eps!=quote.get("eps") or not isinstance(multiples,list) or len(multiples)!=3 or not all(num(v) and 0<v<=100 for v in multiples) or multiples!=sorted(multiples):return result
    prices=[round(eps*v,2) for v in multiples]
    if not all(num(v) for v in prices):return result
    return {**result,"scenario":prices,"scope":"caller_assumed_pe_sensitivity_not_fair_value"}

def historical_valuation(data,quote,now,market):
    result=valuation(data,quote,now,market)
    if not market or not isinstance(data,dict) or data.get("symbol")!=quote["symbol"]:return result
    history=data.get("history")
    if not isinstance(history,list) or not 60<=len(history)<=1500:return result
    try:
        days=[date.fromisoformat(p["date"]) for p in history]
        if days!=sorted(set(days)) or days[-1]>now.date() or (now.date()-days[-1]).days>7 or (days[-1]-days[0]).days<365:return result
        values=[]
        for p,d in zip(history,days):
            published=timestamp(p.get("eps_published_at"))
            observed=timestamp(p.get("observed_at"))
            close=datetime.combine(d,time(13,30),TAIPEI)
            if published is None or observed is None or not published<=close<=observed<=now or not origin(p.get("source_url")):return result
            if not num(p.get("pe")) or not 0<p["pe"]<=100:return result
            price,eps=p.get("raw_price"),p.get("eps")
            if p.get("symbol")!=quote["symbol"] or p.get("eps_basis")!="ttm" or not num(price) or not num(eps) or price<=0 or eps<=0 or not isclose(price/eps,p["pe"],rel_tol=1e-6):return result
            values.append(price/eps)
        quantiles=pd.Series(values).quantile([.25,.5,.75]).tolist()
        eps=quote.get("eps")
        return {**result,"historical_pe":quantiles,"samples":len(values),"historical_scenario":[round(eps*x,2) for x in quantiles] if num(eps) and eps>0 else None,"historical_scope":"snapshot_percentiles_not_fair_value"}
    except (ValueError,TypeError,KeyError):return result
