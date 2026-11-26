"""Single-transaction market audit, bounded batches, no persistence."""
import os,json,time
from contextlib import contextmanager
from app.agents.audit_policy import market_page,source_state
from app.agents.audit_reader import SOURCES
from app.agents.data_auditor import audit
from app.services.v26_coverage_adapter import PREFIXES

@contextmanager
def readonly_session():
    from app.db import Session,engine
    from sqlalchemy import text
    if engine.dialect.name=="sqlite":
        # Pin the physical connection until its original state is restored.
        with engine.connect() as conn:
            original=conn.exec_driver_sql("PRAGMA query_only").scalar_one()
            try:
                conn.exec_driver_sql("PRAGMA query_only=ON")
                conn.exec_driver_sql("BEGIN")
                with Session(bind=conn) as session:
                    yield session
            finally:
                try:
                    conn.rollback()
                    conn.exec_driver_sql("PRAGMA query_only="+("ON" if original else "OFF"))
                    conn.rollback()
                except BaseException:
                    conn.invalidate()
                    raise
        return
    with Session() as session:
        dialect=session.bind.dialect.name
        if dialect=="postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout = '4000ms'"))
        else:
            raise ValueError("unsupported database")
        try:
            yield session
        finally:
            session.rollback()

def aggregate(symbols, rows):
    expected=set(symbols)
    actual=[r["symbol"] for r in rows]
    if len(expected)!=len(symbols) or len(actual)!=len(set(actual)) or set(actual)!=expected:
        raise ValueError("incomplete market")
    total=sum(r["expected_items"] for r in rows)
    complete=sum(r["complete_items"] for r in rows)
    return {"stock_count":len(rows),"expected_items":total,"complete_items":complete,
            "coverage_ratio":complete/total if total else None,
            "mean_quality_score":sum(r["quality_score"] for r in rows)/len(rows) if rows else None}

def read_market(*, now, timeout=30):
    if os.getenv("AGENT_AUDIT_DB_READ")!="1":
        return {"mode":"shadow","status":"denied"}
    from app.db import Document
    from sqlalchemy import select
    deadline=time.monotonic()+min(60,max(1,timeout))
    try:
        with readonly_session() as session:
            record=session.get(Document,"v26:universe:verified_symbols")
            snapshot=json.loads(record.payload) if record else {}
            first=market_page(snapshot,now)
            if not first:raise ValueError("unverified universe")
            symbols=sorted(snapshot["symbols"])
            rows=[]
            priorities=[]
            for offset in range(0,len(symbols),20):
                if time.monotonic()>deadline:raise TimeoutError()
                batch=symbols[offset:offset+20]
                keys=[p+s for s in batch for p in PREFIXES]+["annual:request:"+s for s in batch]
                docs={r.key:json.loads(r.payload) for r in session.scalars(select(Document).where(Document.key.in_(keys)))}
                result=audit(batch,docs,now=now,requests={s:docs.get("annual:request:"+s,{}) for s in batch})
                rows.extend(result["rows"])
                priorities.extend(result["repair_priority"])
            if time.monotonic()>deadline:raise TimeoutError()
            summary=aggregate(symbols,rows)
        from app.agents.audit_policy import rank_repairs
        return {"mode":"shadow","status":"complete","verified":False,"scope":"market_snapshot","snapshot_at":first["snapshot_at"],"summary":summary,"rows":rows,"repair_priority":rank_repairs(priorities,rows,now)}
    except Exception:
        return {"mode":"shadow","status":"unknown","verified":False}
