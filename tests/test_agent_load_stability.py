"""Bounded fault/load tests; no production resources."""
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.api import agent_manager as m
from app.agents.manager_review import ReviewStore
from app.db import put,get

GOOD={"database_ready":True,"failed_jobs":0,"stale_jobs":0}

def test_capacity_and_recovery(monkeypatch):
    entered=threading.Barrier(3)
    release=threading.Event()
    original=m._invoke
    def held(name,payload):
        entered.wait(10)
        assert release.wait(10)
        return original(name,payload)
    monkeypatch.setattr(m,"_invoke",held)
    monkeypatch.setattr(m,"STORE",ReviewStore())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(m.run_once,"fixture",str(i),"system_monitor",GOOD) for i in range(2)]
        try:
            entered.wait(10)
            for name in m.NAMES:
                assert m.run_once("fixture","third",name,{})["status"]=="busy"
            put("agent:test:load",{"value":1})
            assert get("agent:test:load")=={"value":1}
        finally:
            release.set()
        assert all(f.result(timeout=30)["mode"]=="shadow" for f in futures)
    assert not m.PENDING
    monkeypatch.setattr(m,"_invoke",original)
    assert m.invoke("system_monitor",GOOD)["report"]["status"]=="ok"

@pytest.mark.parametrize("name",m.NAMES)
def test_invalid_snapshot_is_contained(name):
    result=m.invoke(name,{"unexpected":None,"positions":"invalid","symbols":False})
    assert result["execution_allowed"] is False
    if name=="recovery":
        report=result["report"]
        assert report["status"]=="planned" and report["executed"] is False
        assert len(report["plans"])==3
        assert {p["source"] for p in report["plans"]}=={"monitor","data","notification"}
        assert all(p["category"]=="unknown" and p["action"]=="collect_evidence" and p["execution_allowed"] is False for p in report["plans"])
    else:
        assert result.get("status",result.get("report",{}).get("status")) in ("unknown","error")
    assert m.invoke("system_monitor",GOOD)["report"]["status"]=="ok"

@pytest.mark.parametrize("script,expected",[
    ("import time; time.sleep(5)","timeout"),
    ("raise SystemExit(7)","unknown"),
    ("print('not json')","unknown"),
    ("print('x'*1000001)","unknown"),
])
def test_real_child_fault_and_slot_release(monkeypatch,script,expected):
    original=m.subprocess.run
    def fault(args,**kwargs):
        kwargs["timeout"]=0.5 if expected=="timeout" else 10
        return original([sys.executable,"-c",script],**kwargs)
    monkeypatch.setattr(m.subprocess,"run",fault)
    assert m.invoke("system_monitor",GOOD)["status"]==expected
    monkeypatch.setattr(m.subprocess,"run",original)
    assert m.invoke("system_monitor",GOOD)["report"]["status"]=="ok"

def test_repeated_real_workers_leave_parent_intact():
    put("agent:test:repeat",{"value":2})
    for i in range(12):
        result=m.invoke("system_monitor",{**GOOD,"failed_jobs":i%2})
        assert result["report"]["status"]==("attention" if i%2 else "ok")
        assert result["execution_allowed"] is False
        assert get("agent:test:repeat")=={"value":2}
    assert not m.PENDING
