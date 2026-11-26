from datetime import datetime,timezone
from app.agents.supervisor import Supervisor
from app.agents.registry import Registry
from app.db import put,get

NOW=datetime(2026,11,26,tzinfo=timezone.utc)

def test_registry():
    assert Registry().resolve("data_auditor") is not None

def test_db_denied(monkeypatch):
    monkeypatch.delenv("AGENT_AUDIT_DB_READ",raising=False)
    assert Supervisor(enabled=True).audit_database(["2330.TW"],now=NOW,is_admin=True)["status"]=="denied"

def test_isolated_read(monkeypatch):
    monkeypatch.setenv("AGENT_AUDIT_DB_READ","1")
    doc={"next_attempt":NOW.timestamp()+60}
    put("annual:source:finmind",doc)
    result=Supervisor(enabled=True).audit_database(["2330.TW"],now=NOW,is_admin=True)
    assert result["source_health"]["finmind"]=="cooldown"
    assert result["rows"][0]["complete_items"]==0
    assert get("annual:source:finmind")==doc
