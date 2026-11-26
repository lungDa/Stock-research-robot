from app.api import agent_manager as m,security
from app.agents.manager_review import ReviewStore,safe_report
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest,sys,subprocess
from copy import deepcopy
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from app.services.trading_calendar import expected_close
from test_agent_risk import position
from test_agent_research import Q,DOC

@pytest.mark.parametrize("name,payload,status",[
("system_monitor",{"database_ready":True,"failed_jobs":0,"stale_jobs":0},"ok"),
("data_auditor",{"symbols":["2330.TW"],"documents":{}},"complete"),
("notification",{"users":[],"documents":{}},"complete"),
("recovery",{"monitor":{"mode":"shadow","checks":[{"code":"database","severity":"critical"}]}},"planned"),
("research",{"symbol":"2330.TW","quote":Q,"documents":DOC},"research_only"),
("risk",{"positions":[position()],"cash":1000},None)])
def test_api_real_worker(monkeypatch,name,payload,status):
    app=FastAPI();app.include_router(m.router)
    app.dependency_overrides[security.current_lighthouse_admin]=lambda:"isolated"
    monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
    monkeypatch.setenv("AGENT_MANAGER_"+name.upper(),"1")
    payload=deepcopy(payload)
    if name=="risk":
        now=datetime.now(ZoneInfo("Asia/Taipei"))
        docs={f"recommendations:calendar:{y}":{"year":y,"closed":[],"opened":[]} for y in (now.year-1,now.year)}
        payload["positions"][0]["research"]["documents"]=docs
        payload["positions"][0]["research"]["quote"]["date"]=str(expected_close(now,docs.get))
    r=TestClient(app).post("/admin/agents/run/"+name,json=payload,headers={"Authorization":"Bearer test"}).json()
    assert r["mode"]=="shadow" and r["execution_allowed"] is False
    assert "report" in r and r["report"].get("status") not in ("unknown","error","denied")
    if status and name!="data_auditor":assert r["report"]["status"]==status

def test_non_admin(monkeypatch):
    monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
    app=FastAPI();app.include_router(m.router)
    app.dependency_overrides[security.current_user]=lambda:"legacy"
    monkeypatch.setattr("app.day_trader.admin_bootstrap.admin_identity_matches",lambda u:False)
    assert TestClient(app).get("/admin/agents/overview").status_code==403

def test_real_timeout(monkeypatch):
    real=subprocess.run
    monkeypatch.setattr(m.subprocess,"run",lambda *a,**k:real([sys.executable,"-c","import time;time.sleep(5)"],timeout=.1,capture_output=True))
    assert m._invoke("risk",{})["status"]=="timeout"

def test_review_isolation():
    s=ReviewStore()
    evidence=s.record("a","token","system_monitor",m.invoke("system_monitor",{"database_ready":False,"failed_jobs":0,"stale_jobs":0}),{})
    p={"monitor":evidence["report"]}
    r=s.record("a","token","recovery",{"mode":"shadow","report":{"status":"planned"}},p)
    plan=r["report"]["plans"][0]
    req={"review_id":r["review_id"],"plan":plan["id"],"version":plan["evidence_version"],"event":"approve","operation_id":"one"}
    assert not s.review("a","other",req)
    assert not s.review("a","token",{**req,"version":"wrong"})
    assert s.review("a","token",req)
    assert not s.review("a","token",req)
    assert s.history("a","other")["runs"]==[]
    assert s.history("a","token")["review"]["executed"] is False
    assert "secret" not in str(safe_report({"token":"secret","report":{"text":"secret"}}))
