"""Conservative shadow policy; no external verification or writes."""
import math
from datetime import date
from urllib.parse import urlsplit
from app.services.v26_coverage_adapter import CODE

def annual_reference(now):
    # General Taiwan calendar-year annual reporting deadline, not issuer-specific.
    return now.year if now.date() >= date(now.year,4,1) else now.year-1

def origin(url):
    try:
        p=urlsplit(url)
        host=p.hostname
        if p.scheme not in ("https","http") or not host or p.username or p.password:
            return None
        for domain in ("twse.com.tw","tpex.org.tw","finmindtrade.com","sec.gov"):
            if host==domain or host.endswith("."+domain):
                return domain
    except (ValueError,TypeError,AttributeError):
        pass
    return None

def source_state(doc, now):
    if not isinstance(doc,dict):
        return "unknown"
    code=doc.get("http_status")
    if code==429:return "rate_limited"
    if code in (401,403):return "authorization_error"
    if type(code) is int and 500<=code<=599:return "upstream_error"
    at=doc.get("next_attempt")
    if type(at) in (int,float) and math.isfinite(at) and at>now.timestamp():return "cooldown"
    return "unknown"

def market_page(snapshot, now, offset=0):
    if type(offset) is not int or offset<0:raise ValueError("invalid offset")
    if not isinstance(snapshot,dict):return None
    at=snapshot.get("at")
    symbols=snapshot.get("symbols")
    if snapshot.get("verified") is not True or snapshot.get("method")!="OFFICIAL_COMPANY_REGISTRY" or type(at) not in (int,float) or not 0<=now.timestamp()-at<=8*86400 or not isinstance(symbols,list) or not 1<=len(symbols)<=5000:
        return None
    if any(not isinstance(s,str) or not CODE.fullmatch(s) for s in symbols) or len(set(symbols))!=len(symbols):return None
    symbols=sorted(symbols)
    return {"symbols":symbols[offset:offset+20],"total":len(symbols),"next_offset":offset+20 if offset+20<len(symbols) else None,"snapshot_at":at}


def rank_repairs(candidates, rows, now):
    from app.services.data_queue import prioritize_missing
    ordered=prioritize_missing(candidates,now=now.timestamp())
    severe={r["symbol"] for r in rows if r["conflicts"] or r["invalid"]}
    # Age promotion prevents permanent starvation by newer conflicts.
    ordered.sort(key=lambda r: (not (r["symbol"] in severe or now.timestamp()-r["requested_at"]>=7*86400),r["requested_at"]))
    return ordered

def provenance(row, field, record):
    meta=row.get("field_sources") or {}
    meta=meta.get(field,{}) if isinstance(meta,dict) else {}
    if not isinstance(meta,dict):meta={}
    # Only explicit original filing identifiers can support same-filing attribution.
    filing=meta.get("original_filing_id")
    return (origin(record.get("source_url")),filing.strip() if isinstance(filing,str) and 0<len(filing.strip())<=256 else None)
