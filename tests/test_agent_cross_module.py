"""Cross-agent contract tests using isolated real workers and snapshot inputs."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from copy import deepcopy
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import agent_manager as m,security
from app.agents.manager_review import ReviewStore
from app.agents.registry import Registry
from app.services.trading_calendar import expected_close
from test_agent_risk import position

def test_cross_agent_pipeline(monkeypatch):
    monkeypatch.setattr(m,"STORE",ReviewStore())
    monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
    app=FastAPI();app.include_router(m.router)
    app.dependency_overrides[security.current_lighthouse_admin]=lambda:"isolated"
    client=TestClient(app)
    headers={"Authorization":"Bearer isolated"}
    for name in m.NAMES:
        assert Registry().resolve(name) is not None
        monkeypatch.setenv("AGENT_MANAGER_"+name.upper(),"1")
    def run(name,payload):
        response=client.post("/admin/agents/run/"+name,json=payload,headers=headers)
        assert response.status_code==200
        result=response.json()
        assert result["mode"]=="shadow" and result["execution_allowed"] is False
        assert result["report"]["snapshot_digest"]==result["snapshot_digest"]
        assert result["report"]["observed_at"]==result["observed_at"]
        return result
    now=datetime.now(ZoneInfo("Asia/Taipei"))
    docs={f"recommendations:calendar:{y}":{"year":y,"closed":[],"opened":[]} for y in (now.year-1,now.year)}
    day=now.date()-timedelta(days=1)
    while day.weekday()>=5:day-=timedelta(days=1)
    docs[f"recommendations:outbox:{day}:morning:fixture"]={"messages":[{"retry_key":"same"},{"retry_key":"same"}]}
    monitor=run("system_monitor",{"database_ready":False,"failed_jobs":1,"stale_jobs":0})
    data=run("data_auditor",{"symbols":["2330.TW"],"documents":docs})
    notification=run("notification",{"users":["fixture"],"documents":docs,"days":7})
    assert any(x["counts"].get("duplicate_risk")==1 for x in notification["report"]["history"])
    recovery=run("recovery",{"monitor":monitor["report"],"data":data["report"],"notification":notification["report"]})
    plans=recovery["report"]["plans"]
    assert {"system_failure","data_missing","notification_duplicate"}<={p["category"] for p in plans}
    assert all(p["execution_allowed"] is False for p in plans)
    assert any(p["category"]=="notification_duplicate" and p["action"]=="hold_and_review" for p in plans)
    p=deepcopy(position())
    p["research"]["documents"]=docs
    p["research"]["quote"]["date"]=str(expected_close(now,docs.get))
    research=run("research",p["research"])
    risk=run("risk",{"positions":[p],"cash":1000})
    assert research["report"]["status"]=="research_only"
    assert risk["report"]["status"]=="risk_only"
    assert risk["report"]["positions"]["2330.TW"]["confidence"]==research["report"]["confidence"]
    assert len(risk["report"]["positions"]["2330.TW"]["research_version"])==64
    history=client.get("/admin/agents/history",headers=headers).json()
    assert len(history["runs"])==6
    assert client.get("/admin/agents/history",headers={"Authorization":"Bearer other"}).json()["runs"]==[]
    plan=next(p for p in plans if p["category"]=="system_failure")
    req={"review_id":recovery["review_id"],"plan":plan["id"],"version":plan["evidence_version"],"event":"approve","operation_id":"integration"}
    assert client.post("/admin/agents/review",json={**req,"version":"wrong"},headers=headers).status_code==409
    assert client.post("/admin/agents/review",json=req,headers=headers).status_code==200
    assert client.post("/admin/agents/review",json=req,headers=headers).status_code==409
