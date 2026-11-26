from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.agent_mount import mount_agent_manager

def test_opt_in_mount_and_runtime_disable(monkeypatch):
    app=FastAPI()
    @app.get("/health")
    def health():return {"status":"ok"}
    monkeypatch.delenv("AGENT_MANAGER_ENABLED",raising=False)
    assert not mount_agent_manager(app)
    with TestClient(app) as c:
        assert c.get("/admin/agents/overview").status_code==404
        assert c.get("/health").status_code==200
        monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
        assert mount_agent_manager(app)
        assert c.get("/admin/agents/overview").status_code==401
        monkeypatch.setenv("AGENT_MANAGER_ENABLED","0")
        for method,path in [("GET","overview"),("GET","history"),("POST","run/system_monitor"),("POST","review"),("POST","clear")]:
            assert c.request(method,"/admin/agents/"+path).status_code==404
        assert c.get("/health").status_code==200

def test_optional_import_failure(monkeypatch):
    import sys
    monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
    monkeypatch.setitem(sys.modules,"app.api.agent_manager",None)
    app=FastAPI()
    assert not mount_agent_manager(app)
    assert not any(r.path.startswith("/admin/agents") for r in app.routes)
