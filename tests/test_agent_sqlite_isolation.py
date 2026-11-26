from sqlalchemy import create_engine,event,text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError
import pytest
from app.agents.audit_aggregate import readonly_session

@pytest.fixture
def isolated_engine(tmp_path,monkeypatch):
    import app.db as db
    engine=create_engine("sqlite:///"+str(tmp_path/"isolated.db"),pool_size=1,max_overflow=0)
    monkeypatch.setattr(db,"engine",engine)
    monkeypatch.setattr(db,"Session",sessionmaker(bind=engine))
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE sample (value integer)")
        c.exec_driver_sql("INSERT INTO sample VALUES (1)")
    yield engine
    engine.dispose()

@pytest.mark.parametrize("original",[0,1])
def test_readonly_restores_original_connection_state(isolated_engine,original):
    with isolated_engine.connect() as c:
        c.exec_driver_sql(f"PRAGMA query_only={original}")
    with pytest.raises(RuntimeError):
        with readonly_session() as s:
            assert s.execute(text("SELECT value FROM sample")).scalar_one()==1
            with pytest.raises(DBAPIError):
                s.execute(text("UPDATE sample SET value=2"))
            raise RuntimeError("injected")
    with isolated_engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA query_only").scalar_one()==original
        assert c.exec_driver_sql("SELECT value FROM sample").scalar_one()==1
        c.exec_driver_sql("PRAGMA query_only=OFF")
        c.exec_driver_sql("UPDATE sample SET value=3")
        c.commit()

def test_readonly_restores_state_on_begin_failure(isolated_engine):
    def fail(conn,cursor,statement,parameters,context,executemany):
        if statement=="BEGIN":
            raise RuntimeError("injected begin failure")
    event.listen(isolated_engine,"before_cursor_execute",fail)
    try:
        with pytest.raises(RuntimeError,match="injected begin failure"):
            with readonly_session():
                pytest.fail("must not enter")
    finally:
        event.remove(isolated_engine,"before_cursor_execute",fail)
    with isolated_engine.begin() as c:
        assert c.exec_driver_sql("PRAGMA query_only").scalar_one()==0
        c.exec_driver_sql("UPDATE sample SET value=3")

@pytest.mark.parametrize("reader",["audit","page","monitor","legacy_monitor"])
def test_reader_paths_preserve_readonly(monkeypatch,reader):
    from datetime import datetime,timezone
    from app.db import engine,put
    from app.agents import audit_reader,monitor_worker_v2,monitor_probe
    now=datetime.now(timezone.utc)
    monkeypatch.setenv("AGENT_AUDIT_DB_READ","1")
    monkeypatch.setenv("AGENT_MONITOR_DB_READ","1")
    put("v26:universe:verified_symbols",{"verified":True,"method":"OFFICIAL_COMPANY_REGISTRY","at":now.timestamp(),"symbols":["2330.TW"]})
    with engine.connect() as c:
        c.exec_driver_sql("PRAGMA query_only=ON")
    try:
        if reader=="audit":
            assert audit_reader.read_audit(["2330.TW"],now=now)["rows"]
        elif reader=="page":
            assert audit_reader.read_market_page(now=now)["rows"]
        elif reader=="monitor":
            assert monitor_worker_v2.run("database")=={"state":"ok"}
        else:
            assert monitor_probe.database()["database"]=="ok"
        with engine.connect() as c:
            assert c.exec_driver_sql("PRAGMA query_only").scalar_one()==1
    finally:
        with engine.connect() as c:
            c.exec_driver_sql("PRAGMA query_only=OFF")
    put("isolation:write_after",{"ok":True})
