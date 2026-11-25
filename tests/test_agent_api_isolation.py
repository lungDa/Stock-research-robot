"""Isolated API integration with real authentication and synthetic identities."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import agent_manager
from app.agents.manager_review import ReviewStore
from app.db import Session
from app.day_trader.access_models import AdminBootstrap
from app.config import settings

ADMIN="U"+"1"*32
OTHER="U"+"2"*32
A={"Authorization":"Bearer "+"a"*24}
B={"Authorization":"Bearer "+"b"*24}
C={"Authorization":"Bearer "+"c"*24}
PREFIX="/admin/agents"
PAYLOAD={"database_ready":True,"failed_jobs":0,"stale_jobs":0}

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings,"users",{"a"*24:ADMIN,"b"*24:OTHER,"c"*24:ADMIN})
    monkeypatch.setattr(settings,"login_channel_id","")
    monkeypatch.setenv("ADMIN_LINE_USER_IDS",OTHER)
    monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
    monkeypatch.setenv("AGENT_MANAGER_SYSTEM_MONITOR","1")
    monkeypatch.setenv("AGENT_MANAGER_RECOVERY","1")
    monkeypatch.setattr(agent_manager,"STORE",ReviewStore())
    with Session.begin() as s:
        s.add(AdminBootstrap(id=1,designated_user=ADMIN,designated_line_user_id=ADMIN,initialized=True))
    app=FastAPI()
    app.include_router(agent_manager.router)
    with TestClient(app) as c:
        yield c

@pytest.mark.parametrize("method,path",[
    ("GET","/overview"),("GET","/history"),("POST","/run/system_monitor"),
    ("POST","/review"),("POST","/clear")])
def test_real_guard_all_routes(client,method,path):
    for headers,code in [({},401),({"Authorization":"Bearer invalid"},403),(B,403)]:
        assert client.request(method,PREFIX+path,headers=headers).status_code==code
    assert not agent_manager.STORE.sessions

def test_same_admin_different_tokens_isolated(client):
    r=client.post(PREFIX+"/run/system_monitor",headers=A,json=PAYLOAD)
    assert r.status_code==200
    assert r.json()["report"]["mode"]=="shadow"
    assert r.json()["execution_allowed"] is False
    assert len(client.get(PREFIX+"/history",headers=A).json()["runs"])==1
    assert client.get(PREFIX+"/history",headers=C).json()["runs"]==[]
    assert client.post(PREFIX+"/review",headers=C,json={"event":"approve","review_id":"foreign"}).status_code==409
    assert client.post(PREFIX+"/clear",headers=C).status_code==200
    assert len(client.get(PREFIX+"/history",headers=A).json()["runs"])==1
    assert client.post(PREFIX+"/clear",headers=A).status_code==200
    assert client.get(PREFIX+"/history",headers=A).json()["runs"]==[]

def test_uninitialized_admin_denied(client):
    with Session.begin() as s:
        s.get(AdminBootstrap,1).initialized=False
    assert client.get(PREFIX+"/overview",headers=A).status_code==403

def test_disabled_and_invalid_requests_do_not_run(client,monkeypatch):
    def forbidden(*a,**k):
        pytest.fail("worker must not run")
    monkeypatch.setattr(agent_manager,"invoke",forbidden)
    assert client.post(PREFIX+"/run/unknown",headers=A,json={}).status_code==404
    assert client.post(PREFIX+"/run/system_monitor",headers=A,content='{"x":NaN}').status_code==400
    assert client.post(PREFIX+"/run/system_monitor",headers=A,content="x"*512001).status_code==413
    monkeypatch.setenv("AGENT_MANAGER_SYSTEM_MONITOR","0")
    assert client.post(PREFIX+"/run/system_monitor",headers=A,json=PAYLOAD).status_code==503
    assert not agent_manager.STORE.sessions
