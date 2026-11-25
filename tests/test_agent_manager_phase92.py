from app.api import agent_manager as m
from app.agents.manager_worker import analyze
from unittest.mock import Mock
import subprocess

def test_monitor_snapshot():
    r=analyze("system_monitor",{"database_ready":True,"failed_jobs":0,"stale_jobs":0})
    assert r["mode"]=="shadow" and r["status"]=="ok"

def test_concurrency():
    assert m.SLOTS.acquire(False)
    assert m.SLOTS.acquire(False)
    try:assert m.invoke("risk",{})["status"]=="busy"
    finally:
        m.SLOTS.release()
        m.SLOTS.release()

def test_digest(monkeypatch):
    def worker(*args,**kwargs):
        kwargs["stdout"].write(b'{"mode":"shadow","status":"ok"}')
        return subprocess.CompletedProcess(args[0],0)
    monkeypatch.setattr(m.subprocess,"run",worker)
    a=m.invoke("risk",{"a":1,"b":2})
    b=m.invoke("risk",{"b":2,"a":1})
    assert a["snapshot_digest"]==b["snapshot_digest"]
    assert a["execution_allowed"] is False

def test_output_limit(monkeypatch):
    def worker(*args,**kwargs):
        kwargs["stdout"].write(b"x"*1000001)
        return subprocess.CompletedProcess(args[0],0)
    monkeypatch.setattr(m.subprocess,"run",worker)
    assert m.invoke("risk",{})=={"mode":"shadow","execution_allowed":False,"status":"unknown"}
