"""Explicitly enabled bounded database snapshot, no provider calls or writes."""
import os
import json
from app.services.v26_coverage_adapter import CODE, PREFIXES
from app.agents.data_auditor import audit

SOURCES=("finmind","sec","mopsfin","twse_eps")

def read_audit(symbols, *, now):
    if os.getenv("AGENT_AUDIT_DB_READ")!="1":
        return {"mode":"shadow","status":"denied","rows":[]}
    if not isinstance(symbols,(list,tuple)) or not 1<=len(symbols)<=20 or any(not isinstance(s,str) or not CODE.fullmatch(s) for s in symbols):
        raise ValueError("invalid symbols")
    from app.db import Session, Document
    from sqlalchemy import select,text
    keys=[p+s for p in PREFIXES for s in set(symbols)]
    keys += ["annual:request:"+s for s in set(symbols)]
    keys += ["annual:source:"+s for s in SOURCES]
    try:
        with Session() as session:
            if session.bind.dialect.name=="postgresql":
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                session.execute(text("SET LOCAL statement_timeout = '4000ms'"))
            elif session.bind.dialect.name=="sqlite":
                session.execute(text("PRAGMA query_only=ON"))
            else:
                return {"mode":"shadow","status":"unknown","rows":[]}
            try:
                docs={r.key:json.loads(r.payload) for r in session.scalars(select(Document).where(Document.key.in_(keys)))}
            finally:
                if session.bind.dialect.name=="sqlite":
                    session.execute(text("PRAGMA query_only=OFF"))
        requests={s:docs.get("annual:request:"+s,{}) for s in set(symbols)}
        result=audit(symbols,docs,now=now,requests=requests)
        result["source_health"]={}
        for name in SOURCES:
            d=docs.get("annual:source:"+name,{})
            at=d.get("next_attempt")
            result["source_health"][name]="cooldown" if type(at) in (int,float) and at>now.timestamp() else "unknown"
        return result
    except Exception:
        return {"mode":"shadow","status":"unknown","rows":[]}
