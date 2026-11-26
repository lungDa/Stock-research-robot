from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import agent_manager,security
from unittest.mock import Mock
def test_guard(monkeypatch):
    monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
    app=FastAPI()
    app.include_router(agent_manager.router)
    c=TestClient(app)
    assert c.get("/admin/agents/overview").status_code==401
    app.dependency_overrides[security.current_lighthouse_admin]=lambda:"admin"
    monkeypatch.delenv("AGENT_MANAGER_ENABLED",raising=False)
    assert c.post("/admin/agents/run/risk",json={}).status_code==503
    assert len(c.get("/admin/agents/overview").json()["agents"])==6
    monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
    monkeypatch.setenv("AGENT_MANAGER_RISK","1")
    fn=Mock(return_value={"mode":"shadow","execution_allowed":False})
    monkeypatch.setattr(agent_manager,"invoke",fn)
    assert c.post("/admin/agents/run/risk",json={}).status_code==200
    fn.assert_called_once()
    assert c.post("/admin/agents/run/risk",content="x"*512001).status_code==413
def test_timeout(monkeypatch):
    import subprocess
    monkeypatch.setattr(agent_manager.subprocess,"run",Mock(side_effect=subprocess.TimeoutExpired("worker",20)))
    assert agent_manager.invoke("risk",{})["status"]=="timeout"
