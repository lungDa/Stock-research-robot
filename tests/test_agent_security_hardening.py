"""Synthetic security regression; no external services."""
import json,sys
import pytest
from app.api import agent_manager as m
from app.agents import manager_review as r
from test_agent_api_isolation import client,A,PREFIX

@pytest.mark.parametrize("raw",['{"x":1,"x":2}','{"x":1e999}','{"x":-1e999}','{"x":'+ '['*40+'0'+']'*40+'}'])
def test_reject_ambiguous_json(client,monkeypatch,raw):
    def forbidden(*a,**k):pytest.fail("worker invoked")
    monkeypatch.setattr(m,"invoke",forbidden)
    assert client.post(PREFIX+"/run/system_monitor",headers=A,content=raw).status_code==400
    assert not m.STORE.sessions

@pytest.mark.parametrize("raw",['{"mode":"shadow","x":1e999}','{"mode":"shadow","mode":"shadow"}'])
def test_worker_output_fail_closed(monkeypatch,raw):
    original=m.subprocess.run
    def fault(args,**kwargs):
        return original([sys.executable,"-c","print("+repr(raw)+")"],**kwargs)
    monkeypatch.setattr(m.subprocess,"run",fault)
    assert m.invoke("system_monitor",{})=={"mode":"shadow","execution_allowed":False,"status":"unknown"}

def test_expired_inflight_session_cannot_recreate(monkeypatch):
    store=r.ReviewStore()
    monkeypatch.setattr(r.time,"monotonic",lambda:100)
    session=store.begin("fixture","token")
    monkeypatch.setattr(r.time,"monotonic",lambda:1001)
    result=store.record("fixture","token","system_monitor",{"mode":"shadow","execution_allowed":False},{},expected=session)
    assert result["status"]=="session_expired"
    assert store.history("fixture","token")["runs"]==[]

def test_worker_environment_allowlist(monkeypatch,tmp_path):
    for key in ("OPENAI_API_KEY","LINE_CHANNEL_ACCESS_TOKEN","GITHUB_TOKEN","DATABASE_URL","PYTHONPATH","LD_PRELOAD"):
        monkeypatch.setenv(key,"synthetic_secret")
    env=m.worker_env(str(tmp_path))
    assert "synthetic_secret" not in env.values()
    assert env["DATABASE_URL"]=="sqlite:///:memory:"
    assert env["PYTHONNOUSERSITE"]=="1"
