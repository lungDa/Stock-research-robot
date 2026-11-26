from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import security, agent_monitor
from app.agents import monitor_worker_v2 as worker
from app.agents.monitor_policy import due_slots
from app.db import put, get

def test_cross_day():
    now=datetime(2026,11,26,12,30,tzinfo=ZoneInfo("Asia/Taipei"))
    def read(key, default=None):
        return {"2026-11-25":True,"2026-11-26":True} if key.endswith("overrides") else default
    slots=due_slots(now,read,[(11,30),(19,30)])
    assert [(s.day,s.hour) for s in slots]==[(25,19),(26,11)]

def test_router_permissions(monkeypatch):
    app=FastAPI()
    app.include_router(agent_monitor.router)
    client=TestClient(app)
    callback=Mock(return_value={"mode":"shadow","status":"ok","checks":[]})
    monkeypatch.setattr(agent_monitor.Supervisor,"monitor",callback)
    monkeypatch.setenv("AGENT_MONITOR_ENABLED","1")
    assert client.get("/admin/agents/system-monitor").status_code==401
    app.dependency_overrides[security.current_user]=lambda:"test-user"
    monkeypatch.setattr(security,"is_admin",lambda user:False)
    assert client.get("/admin/agents/system-monitor").status_code==403
    callback.assert_not_called()
    monkeypatch.setattr(security,"is_admin",lambda user:True)
    monkeypatch.delenv("AGENT_MONITOR_ENABLED")
    assert client.get("/admin/agents/system-monitor").status_code==503
    callback.assert_not_called()
    monkeypatch.setenv("AGENT_MONITOR_ENABLED","1")
    assert client.get("/admin/agents/system-monitor").status_code==200
    callback.assert_called_once()

def test_real_isolated_database(monkeypatch):
    from app.db import engine
    assert engine.dialect.name=="sqlite"
    monkeypatch.setenv("AGENT_MONITOR_DB_READ","1")
    from datetime import timezone
    doc={"state":"finished","updated_at":datetime.now(timezone.utc).isoformat()}
    put("jobs:data_refresh",doc)
    assert worker.run("database")=={"state":"ok"}
    assert worker.run("financial_refresh")=={"state":"ok"}
    assert get("jobs:data_refresh")==doc

def test_api_origin_rejects_other_hosts(monkeypatch):
    monkeypatch.setenv("AGENT_MONITOR_API_URL","https://example.com")
    probe=Mock()
    monkeypatch.setattr(worker.old,"read_json",probe)
    assert worker.run("api_health")=={"state":"unknown"}
    probe.assert_not_called()
