from datetime import datetime,timezone
from app.agents.supervisor import Supervisor
from app.agents.registry import Registry
from app.agents.research import ResearchAgent
NOW=datetime(2026,11,26,12,tzinfo=timezone.utc)
Q={"symbol":"2330.TW","kind":"STOCK","price":100,"date":"2026-11-26","pe":20}
DOC={"recommendations:calendar:2026":{"year":2026,"closed":[],"opened":[]}}
def test_registry_and_denial():
    assert isinstance(Registry().resolve("research"),ResearchAgent)
    assert Supervisor().research(is_admin=True)["status"]=="denied"
    assert Supervisor(enabled=True).research(is_admin=1)["status"]=="denied"
def test_snapshot_only(monkeypatch):
    import app.db
    def forbidden(*a,**k):raise AssertionError("database access")
    monkeypatch.setattr(app.db,"get",forbidden)
    monkeypatch.setattr(app.db,"put",forbidden)
    r=Supervisor(enabled=True).research(is_admin=True,symbol="2330.TW",quote=Q,documents=DOC,now=NOW)
    assert r["status"]=="research_only"
    assert r["confidence"]==0 and r["valuation"]["pe"]==20
    assert r["execution_allowed"] is False and r["verified"] is False
def test_missing_calendar():
    r=ResearchAgent().analyze(symbol="2330.TW",quote=Q,documents={},now=NOW)
    assert r["confidence"]==0 and r["valuation"]["pe"] is None
def test_mismatch():
    assert Supervisor(enabled=True).research(is_admin=True,symbol="2317.TW",quote=Q,documents=DOC,now=NOW)["status"]=="unknown"
