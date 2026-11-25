from app.api import agent_manager as m,security
from app.agents.manager_review import ReviewStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from datetime import datetime,timezone,timedelta
from app.ui import agent_manager as ui

def test_env(monkeypatch,tmp_path):
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN","secret")
    monkeypatch.setenv("DATABASE_URL","postgresql://secret")
    monkeypatch.setenv("OPENAI_API_KEY","secret")
    env=m.worker_env(str(tmp_path))
    assert "secret" not in str(env)
    assert env["DATABASE_URL"]=="sqlite:///:memory:"
    assert env["PYTHON_DOTENV_DISABLED"]=="1"

def test_review_limit(monkeypatch):
    app=FastAPI();app.include_router(m.router)
    app.dependency_overrides[security.current_lighthouse_admin]=lambda:"admin"
    monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
    monkeypatch.setenv("AGENT_MANAGER_RECOVERY","1")
    assert TestClient(app).post("/admin/agents/review",content="x"*4097).status_code==413

def test_stale_and_clear():
    s=ReviewStore()
    p={"monitor":{"observed_at":(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),"mode":"shadow","checks":[{"code":"database","severity":"critical"}]}}
    r=s.record("a","token","recovery",{"mode":"shadow","report":{"status":"planned"}},p)
    assert "review_id" not in r
    s.record("a","token","risk",{"mode":"shadow","status":"unknown"},{})
    assert s.history("a","token")["runs"]
    s.clear("a","token")
    assert not s.history("a","token")["runs"]

def test_ui_clear(monkeypatch):
    state={"agent_manager_cache":{"owner":"a"},"agent_manager_snapshot":"private","token":"b"}
    monkeypatch.setattr(ui.st,"session_state",state)
    ui.clear()
    assert state=={"token":"b"}
