"""Snapshot-only Taiwan equity research; no fetch, persistence or AI."""
from datetime import date, datetime
import re, json, hashlib
from copy import deepcopy
from math import isfinite,sqrt
from statistics import stdev
from app.services import analysis, multifactor
from app.services.freshness import TAIPEI
from app.services.trading_calendar import status
from app.services.v26_coverage_adapter import CODE
from app.day_trader.technical import score
from app.agents.data_auditor import DataAuditor
from app.agents.research_evidence import annual_evidence, technical_evidence, downside, historical_valuation, timestamp
from app.agents.audit_policy import origin

def number(v):
    return type(v) in (int,float) and isfinite(v)

class ResearchAgent:
    def analyze(self, *, symbol, quote, documents, now, config=None, bars=None, defensive=None, valuation_inputs=None):
        if not isinstance(symbol,str) or not re.fullmatch(r"\d{4,6}[A-Z]?\.(TW|TWO)",symbol) or not isinstance(now,datetime) or now.utcoffset() is None:
            raise ValueError("invalid research scope")
        now=now.astimezone(TAIPEI)
        if not isinstance(quote,dict) or quote.get("symbol")!=symbol or quote.get("kind") not in ("STOCK","ETF") or not isinstance(documents,dict) or len(documents)>100:
            raise ValueError("invalid snapshot")
        quote,documents,config,bars,defensive,valuation_inputs=deepcopy((quote,documents,config,bars,defensive,valuation_inputs))
        kind=quote["kind"]
        if kind=="STOCK" and not CODE.fullmatch(symbol):raise ValueError("stock code")
        c=multifactor.validate(multifactor.DEFAULT if config is None else config)
        if kind=="ETF" or "classification" in quote:
            meta=quote.get("classification",{})
            at=timestamp(meta.get("observed_at"))
            if meta.get("symbol")!=symbol or meta.get("kind")!=kind or origin(meta.get("source_url")) not in ("twse.com.tw","tpex.org.tw") or at is None or not 0<=(now-at).total_seconds()<=8*86400:raise ValueError("classification evidence")
        version=hashlib.sha256(json.dumps([symbol,quote,documents,c,bars,defensive,valuation_inputs,now.isoformat()],sort_keys=True,allow_nan=False).encode()).hexdigest()
        def market(q,today=None):
            return q.get("data_status") not in ("stale","fundamentals_only") and number(q.get("price")) and q["price"]>0 and status(q,now,documents.get)["state"]=="current"
        audit=DataAuditor().audit([symbol],documents,now=now)["rows"][0] if kind=="STOCK" else None
        rows,evidence=annual_evidence(symbol,multifactor.annual_rows("__shadow__",symbol,documents=documents),documents,now,audit) if audit else ({},[])
        technical=technical_evidence(bars,quote,now,documents,market(quote))
        for k in ("ma20","ma60","adjusted_close","volume_ratio","volatility"):quote.pop(k,None)
        if technical["complete"]:
            quote.update(ma20=technical["ma20"],ma60=technical["ma60"],adjusted_close=bars[-1]["close"],volume_ratio=technical["relative_volume"])
            closes=[b["close"] for b in bars]
            returns=[b/a-1 for a,b in zip(closes,closes[1:])]
            if all(number(v) for v in returns):quote["volatility"]=stdev(returns)*sqrt(252)*100
        if kind=="ETF":
            for k in ("yield","expense_ratio"):
                meta=quote.get(k+"_evidence",{})
                at=timestamp(meta.get("observed_at"))
                if not origin(meta.get("source_url")) or at is None or not 0<=(now-at).total_seconds()<=30*86400 or not number(quote.get(k)) or quote[k]<0:quote.pop(k,None)
        factors=multifactor.evaluate(quote,c,rows,now.date(),market_check=market)
        income=analysis.evaluate(quote,"income",market_check=market)
        swing=analysis.evaluate(quote,"swing",market_check=market)
        defense=downside(defensive,symbol,now,documents)
        value=historical_valuation(valuation_inputs,quote,now,market(quote)) if kind=="STOCK" else {"scope":"not_applicable_etf"}
        # Confidence measures coverage, not investment success probability.
        confidence=min(audit["quality_score"],factors["coverage"]) if audit and market(quote) else factors["coverage"] if market(quote) else 0
        if audit and (audit["conflicts"] or audit["invalid"] or audit["stale_sources"]):
            confidence=0
        if factors["required_missing"]:confidence=0
        return {"mode":"shadow","status":"research_only","symbol":symbol,"kind":kind,"schema_version":1,"evidence_version":version,"as_of":now.isoformat(),
                "execution_allowed":False,"verified":False,"confidence":confidence,
                "confidence_basis":"provisional_rule_coverage_not_return_probability","classification_verified":False,"classification_scope":"caller_metadata_checked" if "classification" in quote else "stock_code_and_quote_only",
                "financial_audit":audit,"annual_evidence":evidence,
                "component_confidence":{"financial":confidence if audit else None,"etf":confidence if kind=="ETF" else None,"market":100 if market(quote) else 0,"technical":min(100,round(100*technical["samples"]/252)) if technical["complete"] else 0,"defensive":min(100,round(100*defense["pairs"]/252),round(100*defense["down_sessions"]/60)) if defense["status"]=="available" else 0,"valuation":min(100,round(100*value.get("samples",0)/252)) if value.get("historical_scenario") else 0},"factors":{k:factors.get(k) for k in ("score","coverage","checks","config_hash","required_missing")},
                "income":income,"swing":swing,"technical":technical,
                "valuation":value,"defensive":defense}

    def batch(self, *, snapshots, now, config=None):
        if not isinstance(snapshots,list) or not 1<=len(snapshots)<=20:raise ValueError("batch size")
        c=multifactor.validate(multifactor.DEFAULT if config is None else config)
        symbols=[x.get("symbol") for x in snapshots if isinstance(x,dict) and isinstance(x.get("symbol"),str)]
        if len(set(symbols))!=len(symbols):raise ValueError("duplicate symbols")
        reports=[]
        errors=[]
        for i,x in enumerate(snapshots):
            try:reports.append(self.analyze(now=now,config=c,**x))
            except Exception:errors.append({"index":i,"status":"invalid_snapshot"})
        groups={}
        for kind in ("STOCK","ETF"):
            eligible=[r for r in reports if r["kind"]==kind and r["confidence"]>0 and r["factors"]["coverage"]==100 and r["factors"]["score"] is not None]
            groups[kind]=[r["symbol"] for r in sorted(eligible,key=lambda r:(-r["factors"]["score"],-r["confidence"],r["symbol"]))]
        return {"mode":"shadow","status":"research_only","execution_allowed":False,"reports":reports,"errors":errors,"comparison":groups,"scope":"rule_score_comparison_not_trade_ranking"}
