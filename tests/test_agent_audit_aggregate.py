from datetime import datetime,timezone
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.agents.audit_aggregate import readonly_session,aggregate
from app.agents.supervisor import Supervisor
from app.db import put,get,Document
NOW=datetime(2026,11,26,tzinfo=timezone.utc)

def test_readonly_rejects_write():
    with readonly_session() as session:
        assert session.bind.dialect.name=="sqlite"
        with pytest.raises(DBAPIError):
            session.execute(text("CREATE TABLE audit_forbidden_test (id integer)"))
    put("audit:test",{"ok":True})
    assert get("audit:test")=={"ok":True}

def test_market_snapshot(monkeypatch):
    monkeypatch.setenv("AGENT_AUDIT_DB_READ","1")
    snapshot={"verified":True,"method":"OFFICIAL_COMPANY_REGISTRY","at":NOW.timestamp(),"symbols":[f"{i}.TW" for i in range(1000,1021)]}
    put("v26:universe:verified_symbols",snapshot)
    result=Supervisor(enabled=True).audit_market_snapshot(now=NOW,is_admin=True)
    assert result["status"]=="complete"
    assert result["summary"]["stock_count"]==21
    assert result["verified"] is False
    assert get("v26:universe:verified_symbols")==snapshot

def test_aggregate_rejects_duplicates():
    with pytest.raises(ValueError):
        aggregate(["2330.TW"],[{"symbol":"2330.TW"},{"symbol":"2330.TW"}])

def test_aggregate_denied():
    assert Supervisor().audit_market_snapshot(now=NOW,is_admin=True)["status"]=="denied"
