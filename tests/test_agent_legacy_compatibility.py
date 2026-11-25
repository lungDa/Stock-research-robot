"""Legacy behavior remains unchanged after isolated Agent execution."""
from copy import deepcopy
from fastapi.testclient import TestClient
from app.api.server import app
from app.api.agent_manager import invoke
from app.services import analysis,multifactor,freshness
from test_multifactor import annual,quote,TODAY
from test_api import A,B

def test_legacy_analysis_contract(monkeypatch):
    monkeypatch.setattr(freshness,"market_usable",lambda q:True)
    q=quote()
    q.update(eps=3,roe=.2,pe=20,yield_basis="trailing_paid_365d",**{"yield":5})
    before=deepcopy(q)
    for mode in ("income","swing"):
        assert analysis.evaluate(q,mode)==analysis.evaluate(q,mode,market_check=lambda q:True)
        assert all(v is None for v in analysis.evaluate(q,mode,market_check=lambda q:False)["checks"].values())
    assert q==before

def test_legacy_multifactor_contract(monkeypatch):
    monkeypatch.setattr(freshness,"market_usable",lambda q,today=None:True)
    q=quote();rows=annual()
    before=deepcopy((q,rows))
    assert multifactor.evaluate(q,multifactor.DEFAULT,rows,TODAY)==multifactor.evaluate(q,multifactor.DEFAULT,rows,TODAY,market_check=lambda q,today=None:True)
    assert (q,rows)==before

def test_legacy_api_survives_shadow_worker(monkeypatch):
    monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
    monkeypatch.setenv("AGENT_MANAGER_SYSTEM_MONITOR","1")
    with TestClient(app) as client:
        assert client.post("/watchlist",headers=A,json={"symbol":"AAPL"}).status_code==200
        before=client.get("/watchlist",headers=A).json()
        other=client.get("/watchlist",headers=B).json()
        result=invoke("system_monitor",{"database_ready":False,"failed_jobs":1,"stale_jobs":0})
        assert result["report"]["mode"]=="shadow"
        assert result["execution_allowed"] is False
        assert client.get("/watchlist",headers=A).json()==before
        assert client.get("/watchlist",headers=B).json()==other
        assert client.get("/health").status_code==200
        assert client.get("/admin/agents/overview",headers=A).status_code==404
