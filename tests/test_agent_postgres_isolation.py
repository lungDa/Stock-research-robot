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
    engine=create_engine("postgresql+psycopg://agent_test:agent_test@127.0.0.1:55432/agent_isolated",pool_size=2,max_overflow=0,connect_args={"connect_timeout":5})
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
