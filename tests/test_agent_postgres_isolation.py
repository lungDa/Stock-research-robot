"""Real PostgreSQL integration; only a disposable CI service, never DATABASE_URL."""
import os
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError
from app.agents.audit_aggregate import readonly_session

@pytest.fixture
def pg(monkeypatch):
    if os.getenv("AGENT_PG_ISOLATED_CI")!="1":
        pytest.skip("requires disposable PostgreSQL CI service")
    import app.db as db
    # Fixed loopback endpoint and synthetic credentials; no production URL accepted.
    engine=create_engine("postgresql+psycopg://agent_test:agent_test@127.0.0.1:55432/agent_isolated",pool_size=2,max_overflow=0,pool_timeout=0.5,pool_pre_ping=True,connect_args={"connect_timeout":5})
    monkeypatch.setattr(db,"engine",engine)
    monkeypatch.setattr(db,"Session",sessionmaker(bind=engine))
    try:
        with engine.begin() as c:
            assert c.execute(text("SELECT current_database()")).scalar_one()=="agent_isolated"
            c.execute(text("CREATE TABLE IF NOT EXISTS agent_probe (value integer)"))
            c.execute(text("TRUNCATE agent_probe"))
            c.execute(text("INSERT INTO agent_probe VALUES (1)"))
        yield engine
    finally:
        engine.dispose()

@pytest.mark.parametrize("sql",["INSERT INTO agent_probe VALUES (2)","UPDATE agent_probe SET value=2","DELETE FROM agent_probe","CREATE TABLE agent_forbidden (id integer)"])
def test_postgres_readonly(pg,sql):
    with pytest.raises(DBAPIError) as exc:
        with readonly_session() as s:
            assert s.execute(text("SHOW transaction_read_only")).scalar_one()=="on"
            assert s.execute(text("SHOW transaction_isolation")).scalar_one()=="repeatable read"
            assert s.execute(text("SELECT value FROM agent_probe")).scalar_one()==1
            s.execute(text(sql))
    assert exc.value.orig.sqlstate=="25006"
    with pg.begin() as c:
        assert c.execute(text("SHOW transaction_read_only")).scalar_one()=="off"
        assert c.execute(text("SELECT value FROM agent_probe")).scalar_one()==1
        c.execute(text("UPDATE agent_probe SET value=3"))

def test_postgres_snapshot(pg):
    with readonly_session() as s:
        assert s.execute(text("SELECT value FROM agent_probe")).scalar_one()==1
        with pg.begin() as c:
            c.execute(text("UPDATE agent_probe SET value=2"))
        assert s.execute(text("SELECT value FROM agent_probe")).scalar_one()==1
    with pg.connect() as c:
        assert c.execute(text("SELECT value FROM agent_probe")).scalar_one()==2

def test_postgres_timeout_and_recovery(pg):
    with pytest.raises(DBAPIError) as exc:
        with readonly_session() as s:
            assert s.execute(text("SHOW statement_timeout")).scalar_one()=="4s"
            s.execute(text("SELECT pg_sleep(5)"))
    assert exc.value.orig.sqlstate=="57014"
    with pg.begin() as c:
        assert c.execute(text("SHOW statement_timeout")).scalar_one()=="0"
        c.execute(text("UPDATE agent_probe SET value=4"))

def test_postgres_exception_cleanup(pg):
    with pytest.raises(RuntimeError,match="injected"):
        with readonly_session() as s:
            s.execute(text("SELECT 1"))
            raise RuntimeError("injected")
    with pg.begin() as c:
        assert c.execute(text("SHOW transaction_read_only")).scalar_one()=="off"
        c.execute(text("UPDATE agent_probe SET value=5"))


def test_connection_failure_and_recovery(pg,monkeypatch):
    from datetime import datetime,timezone
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from app.agents.audit_reader import read_audit
    monkeypatch.setenv("AGENT_AUDIT_DB_READ","1")
    pg.dispose()
    def unavailable(*args,**kwargs):
        raise OperationalError("synthetic connect failure",None,Exception("unavailable"))
    event.listen(pg,"do_connect",unavailable)
    try:
        assert read_audit(["2330.TW"],now=datetime.now(timezone.utc))=={"mode":"shadow","status":"unknown","rows":[]}
    finally:
        event.remove(pg,"do_connect",unavailable)
    with readonly_session() as s:
        assert s.execute(text("SELECT value FROM agent_probe")).scalar_one()==1

def test_pool_exhaustion(pg):
    import time
    from sqlalchemy.exc import TimeoutError
    with pg.connect(),pg.connect():
        start=time.monotonic()
        with pytest.raises(TimeoutError):
            with readonly_session():
                pytest.fail("exhausted pool unexpectedly acquired")
        assert 0.4<=time.monotonic()-start<3
    assert pg.pool.checkedout()==0
    with readonly_session() as s:
        assert s.execute(text("SELECT 1")).scalar_one()==1

def test_lock_timeout(pg):
    with pg.begin() as writer:
        writer.execute(text("LOCK TABLE agent_probe IN ACCESS EXCLUSIVE MODE"))
        with pytest.raises(DBAPIError) as exc:
            with readonly_session() as s:
                s.execute(text("SELECT value FROM agent_probe"))
        assert exc.value.orig.sqlstate=="57014"
    with readonly_session() as s:
        assert s.execute(text("SELECT value FROM agent_probe")).scalar_one()==1

def test_disconnect_during_transaction(pg):
    with pytest.raises(DBAPIError):
        with readonly_session() as s:
            pid=s.execute(text("SELECT pg_backend_pid()")).scalar_one()
            with pg.begin() as killer:
                assert killer.execute(text("SELECT pg_terminate_backend(:pid)"),{"pid":pid}).scalar_one()
            s.execute(text("SELECT 1"))
    assert pg.pool.checkedout()==0
    with readonly_session() as s:
        assert s.execute(text("SELECT value FROM agent_probe")).scalar_one()==1

def test_stale_idle_connection(pg):
    with pg.connect() as first:
        pid=first.execute(text("SELECT pg_backend_pid()")).scalar_one()
        with pg.begin() as killer:
            assert killer.execute(text("SELECT pg_terminate_backend(:pid)"),{"pid":pid}).scalar_one()
        # Invalidate on close if rollback detects the dead socket.
        first.invalidate()
    with readonly_session() as s:
        assert s.execute(text("SELECT value FROM agent_probe")).scalar_one()==1

def test_failed_reader_does_not_abort_other_transaction(pg):
    with pg.begin() as writer:
        writer.execute(text("UPDATE agent_probe SET value=8"))
        with pytest.raises(DBAPIError):
            with readonly_session() as s:
                assert s.execute(text("SELECT value FROM agent_probe")).scalar_one()==1
                s.execute(text("SELECT 1/0"))
        assert writer.execute(text("SELECT value FROM agent_probe")).scalar_one()==8
    with readonly_session() as s:
        assert s.execute(text("SELECT value FROM agent_probe")).scalar_one()==8

def test_repeated_failures_leave_data_and_pool_intact(pg):
    for _ in range(3):
        with pytest.raises(DBAPIError):
            with readonly_session() as s:
                s.execute(text("SELECT 1/0"))
        assert pg.pool.checkedout()==0
    with pg.begin() as c:
        assert c.execute(text("SELECT value FROM agent_probe")).scalar_one()==1
        assert c.execute(text("SHOW transaction_read_only")).scalar_one()=="off"
        c.execute(text("UPDATE agent_probe SET value=9"))


def test_idle_dead_connection_detected_by_pre_ping(pg):
    # Hold the second connection so the next checkout must reuse the dead
    # idle slot. No explicit invalidate() or dispose() after termination.
    with pg.connect() as killer:
        with pg.connect() as idle:
            pid=idle.execute(text("SELECT pg_backend_pid()")).scalar_one()
        assert pg.pool.checkedout()==1
        assert killer.execute(text("SELECT pg_terminate_backend(:pid, 5000)"),{"pid":pid}).scalar_one()
        killer.commit()
        with readonly_session() as s:
            new_pid=s.execute(text("SELECT pg_backend_pid()")).scalar_one()
            assert new_pid!=pid
            assert s.execute(text("SHOW transaction_read_only")).scalar_one()=="on"
            assert s.execute(text("SELECT value FROM agent_probe")).scalar_one()==1
        assert pg.pool.checkedout()==1
    assert pg.pool.checkedout()==0
    with pg.begin() as c:
        assert c.execute(text("SHOW transaction_read_only")).scalar_one()=="off"
        assert c.execute(text("SELECT value FROM agent_probe")).scalar_one()==1
