"""Conservative snapshot evidence adapters. No network or database reads."""
from datetime import date,timedelta
from math import isfinite
from app.agents.audit_policy import origin
from app.services.v26_coverage_adapter import PREFIXES,_record
from jobs.v26_six_factor_coverage import valid_record
from app.services.trading_calendar import session
from app.day_trader.technical import score
from app.services.defensive_model import downside_statistics
import pandas as pd

FIELDS=("eps","roe_pct","cash_yield_pct","cash_dividend_per_share","cash_dividends_paid","operating_cash_flow","capital_expenditure","revenue")
def num(v):
    return type(v) in (int,float) and isfinite(v)

def annual_evidence(symbol,rows,documents,now):
    clean={}
    evidence=[]
    for year,row in rows.items():
        if not isinstance(year,str) or not year.isdigit() or len(year)!=4 or not now.year-11<=int(year)<now.year:continue
        for field in FIELDS:
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
                stamp=doc.get("at")
                if not num(stamp) or not 0<=now.timestamp()-stamp<=(30 if prefix=="annual:shared:" else 90)*86400:continue
                if r["value"]!=v:conflict=True
                else:matches.append((prefix,r))
            if conflict or not matches:continue
            prefix,r=matches[0]
            clean.setdefault(year,{})[field]=v
            evidence.append({"field":field,"year":year,"source":prefix,"origin":origin(r["source_url"]),"unit":r["unit"],"period_end":r["period_end"],"value":v})
    # Require compatible units for cash-flow arithmetic and cross-year series.
    for field in FIELDS:
        if len({e["unit"] for e in evidence if e["field"]==field})>1:
            for row in clean.values():row.pop(field,None)
    for year,row in clean.items():
        units={e["unit"] for e in evidence if e["year"]==year and e["field"] in ("operating_cash_flow","capital_expenditure","cash_dividends_paid")}
        if len(units)>1:
            for field in ("operating_cash_flow","capital_expenditure","cash_dividends_paid"):row.pop(field,None)
    return clean,[e for e in evidence if e["field"] in clean.get(e["year"],{})]

def technical_evidence(bars,quote,now,documents,market):
    missing={"complete":False,"score":None}
    if not market or quote.get("adjustment_status")!="verified" or not isinstance(bars,list) or not 60<=len(bars)<=1000:return missing
    try:
        days=[date.fromisoformat(b["date"]) for b in bars]
        if days!=sorted(set(days)) or days[-1].isoformat()!=quote["date"]:return missing
        if (days[-1]-days[0]).days>2000:return missing
        if any(b.get("symbol")!=quote["symbol"] or b.get("completed") is not True or b.get("adjustment_status")!="verified" for b in bars):return missing
        expected=[days[0]+timedelta(days=i) for i in range((days[-1]-days[0]).days+1)]
        states=[session(d,documents.get) for d in expected]
        if None in states or [d for d,v in zip(expected,states) if v]!=days:return missing
        if not num(quote.get("adjusted_close")) or bars[-1]["close"]!=quote["adjusted_close"]:return missing
        return score(bars)
    except (ValueError,TypeError,KeyError):return missing

def downside(data,symbol,now,documents):
    missing={"status":"insufficient_data"}
    if not isinstance(data,dict) or data.get("symbol")!=symbol or data.get("adjustment_status")!="verified" or data.get("alignment")!="released_before_taiwan_open":return missing
    try:
        pairs=data["pairs"]
        if not isinstance(pairs,list) or not 60<=len(pairs)<=1500:return missing
        days=[date.fromisoformat(p["date"]) for p in pairs]
        if days!=sorted(set(days)) or days[-1]>now.date() or (now.date()-days[-1]).days>7:return missing
        if any(session(d,documents.get) is not True for d in days):return missing
        if any(not num(p[k]) or p[k]<-1 for p in pairs for k in ("stock","benchmark")):return missing
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
