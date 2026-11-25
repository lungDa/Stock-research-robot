"""Bounded shadow audit of existing financial documents; no provider calls."""
import math
from app.services.v26_coverage_adapter import CODE, PREFIXES, FIELDS, from_documents, _record
from jobs.v26_six_factor_coverage import valid_record
from app.services.data_queue import prioritize_missing

def audit(symbols, documents, *, now):
    if not isinstance(symbols,(list,tuple)) or not 1<=len(symbols)<=20 or any(not isinstance(s,str) or not CODE.fullmatch(s) for s in symbols):
        raise ValueError("invalid symbols")
    if now.tzinfo is None:
        raise ValueError("timezone required")
    rows=[]
    priorities=[]
    for symbol in sorted(set(symbols)):
        docs={}
        stale=unknown=0
        conflicts=[]
        invalid=[]
        observations={}
        for prefix in PREFIXES:
            key=prefix+symbol
            doc=documents.get(key)
            if not isinstance(doc,dict) or not isinstance(doc.get("rows"),dict):
                unknown+=1
                continue
            stamp=doc.get("at")
            if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<=now.timestamp()-stamp:
                unknown+=1
            elif now.timestamp()-stamp>7*86400:
                stale+=1
            clean={}
            for year,row in doc["rows"].items():
                if not isinstance(year,str) or not year.isdigit() or len(year)!=4 or not now.year-10<=int(year)<now.year or not isinstance(row,dict):
                    continue
                clean[year]=dict(row)
                for field in FIELDS:
                    value=row.get(field)
                    if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or (field in ("cash_yield_pct","cash_dividend_years") and value<0)):
                        invalid.append((field,year))
                        clean[year].pop(field,None)
                        continue
                    rec=_record(clean[year],field,int(year))
                    if rec and valid_record(rec,int(year),field):
                        # Compare only matching periods, units and calculation bases.
                        basis=tuple(str(rec.get(k)) for k in ("unit","period_end","cashflow_basis","price_date","dividend_basis","price_source"))
                        if rec.get("unit") and rec.get("period_end")==year+"-12-31":
                            observations.setdefault((field,year,basis),[]).append(rec["value"])
            docs[key]={"rows":clean}
        for (field,year,basis),values in observations.items():
            if len(values)>1 and any(not math.isclose(v,values[0],rel_tol=0.01,abs_tol=0.01) for v in values[1:]):
                conflicts.append((field,year))
        result=from_documents(symbol,docs,current_year=now.year)
        missing=result["expected_items"]-result["complete_items"]
        issues=len(set(conflicts+invalid))
        score=round(100*result["coverage_ratio"]*max(0,1-issues/result["expected_items"])*max(0,1-(stale+unknown)/len(PREFIXES)),2)
        rows.append({"symbol":symbol,"complete_items":result["complete_items"],"expected_items":result["expected_items"],"missing_years":result["missing_years"],"stale_sources":stale,"unknown_sources":unknown,"conflicts":sorted(set(conflicts)),"invalid":sorted(set(invalid)),"quality_score":score})
        if missing or issues or stale or unknown:
            priorities.append({"symbol":symbol,"missing_fields":missing,"requested_at":now.timestamp()})
    return {"mode":"shadow","verified":False,"scope":"requested_symbols_only","rows":rows,"repair_priority":prioritize_missing(priorities,now=now.timestamp())}
