"""Explicitly enabled bounded database snapshot, no provider calls or writes."""
import os
import json
from app.agents.audit_policy import source_state, market_page
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
            result["source_health"][name]=source_state(d,now)
        return result
    except Exception:
        return {"mode":"shadow","status":"unknown","rows":[]}


def read_market_page(*, now, offset=0, expected_snapshot_at=None):
    if os.getenv("AGENT_AUDIT_DB_READ")!="1":
        return {"mode":"shadow","status":"denied","rows":[]}
    from app.db import Session, Document
    from sqlalchemy import text
    try:
        with Session() as session:
            if session.bind.dialect.name=="postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(text("SET LOCAL statement_timeout = '4000ms'"))
            elif session.bind.dialect.name!="sqlite":
                return {"mode":"shadow","status":"unknown","rows":[]}
            row=session.get(Document,"v26:universe:verified_symbols")
            page=market_page(json.loads(row.payload) if row else {},now,offset)
        if not page or not page["symbols"] or (offset and expected_snapshot_at!=page["snapshot_at"]):
            return {"mode":"shadow","status":"unknown","rows":[]}
        result=read_audit(page["symbols"],now=now)
        result.update(scope="market_page_only",market_total=page["total"],next_offset=page["next_offset"],snapshot_at=page["snapshot_at"])
        return result
    except Exception:
        return {"mode":"shadow","status":"unknown","rows":[]}
