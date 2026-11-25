"""Snapshot-only Taiwan equity research; no fetch, persistence or AI."""
from datetime import date, datetime
from math import isfinite
from app.services import analysis, multifactor
from app.services.freshness import TAIPEI
from app.services.trading_calendar import status
from app.services.v26_coverage_adapter import CODE
from app.day_trader.technical import score
from app.agents.data_auditor import DataAuditor
from app.agents.research_evidence import annual_evidence, technical_evidence, downside, valuation

def number(v):
    return type(v) in (int,float) and isfinite(v)

class ResearchAgent:
    def analyze(self, *, symbol, quote, documents, now, config=None, bars=None, defensive=None, valuation_inputs=None):
        if not isinstance(symbol,str) or not CODE.fullmatch(symbol) or not isinstance(now,datetime) or now.utcoffset() is None:
            raise ValueError("invalid research scope")
        now=now.astimezone(TAIPEI)
        if not isinstance(quote,dict) or quote.get("symbol")!=symbol or quote.get("kind")!="STOCK" or not isinstance(documents,dict) or len(documents)>100:
            raise ValueError("invalid snapshot")
        c=multifactor.validate(multifactor.DEFAULT if config is None else config)
        def market(q,today=None):
            return q.get("data_status") not in ("stale","fundamentals_only") and number(q.get("price")) and q["price"]>0 and status(q,now,documents.get)["state"]=="current"
        audit=DataAuditor().audit([symbol],documents,now=now)["rows"][0]
        rows=multifactor.annual_rows("__shadow__",symbol,documents=documents)
        rows, evidence=annual_evidence(symbol,rows,documents,now)
        factors=multifactor.evaluate(quote,c,rows,now.date(),market_check=market)
        income=analysis.evaluate(quote,"income",market_check=market)
        swing=analysis.evaluate(quote,"swing",market_check=market)
        technical=technical_evidence(bars,quote,now,documents,market(quote))
        defense=downside(defensive,symbol,now,documents)
        value=valuation(valuation_inputs,quote,now,market(quote))
        # Confidence measures coverage, not investment success probability.
        confidence=min(audit["quality_score"],factors["coverage"]) if market(quote) else 0
        if audit["conflicts"] or audit["invalid"] or audit["stale_sources"]:
            confidence=0
        if factors["required_missing"]:confidence=0
        return {"mode":"shadow","status":"research_only","symbol":symbol,"as_of":now.isoformat(),
                "execution_allowed":False,"verified":False,"confidence":confidence,
                "confidence_basis":"provisional_financial_coverage_not_return_probability",
                "financial_audit":audit,"annual_evidence":evidence,
                "component_confidence":{"financial":confidence,"market":100 if market(quote) else 0,"technical":100 if technical["complete"] else 0,"defensive":100 if defense["status"]=="available" else 0,"valuation":100 if value.get("scenario") else 0},"factors":{k:factors.get(k) for k in ("score","coverage","checks","config_hash","required_missing")},
                "income":income,"swing":swing,"technical":technical,
                "valuation":value,"defensive":defense}
