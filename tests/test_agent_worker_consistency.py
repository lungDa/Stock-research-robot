"""Real subprocess boundary: canonical snapshots, no parent state inheritance."""
import hashlib
import json
import os
import pytest
from app.api import agent_manager as api
from app.db import put,get

@pytest.mark.parametrize("payload",[
    {"database_ready":True,"failed_jobs":0,"stale_jobs":0},
    {"database_ready":False,"failed_jobs":2,"stale_jobs":1},
    {"database_ready":None,"failed_jobs":None,"stale_jobs":None},
])
def test_worker_snapshot_digest_and_repeatability(payload):
    first=api.invoke("system_monitor",payload)
    second=api.invoke("system_monitor",dict(reversed(list(payload.items()))))
    canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False)
    digest=hashlib.sha256(("system_monitor:"+canonical).encode()).hexdigest()
    assert first["snapshot_digest"]==second["snapshot_digest"]==digest
    assert first["report"]==second["report"]
    assert first["execution_allowed"] is second["execution_allowed"] is False
    assert first["report"]["mode"]=="shadow"

def test_worker_reports_follow_snapshot_not_parent_state(monkeypatch):
    marker="agent:test:worker-boundary"
    put(marker,{"database_ready":False,"failed_jobs":99})
    monkeypatch.setenv("DATABASE_URL","sqlite:///never-use-parent-snapshot.db")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN","synthetic-not-inherited")
    monkeypatch.setenv("OPENAI_API_KEY","synthetic-not-inherited")
    good={"database_ready":True,"failed_jobs":0,"stale_jobs":0}
    bad={**good,"database_ready":False}
    a=api.invoke("system_monitor",good)
    b=api.invoke("system_monitor",bad)
    assert a["report"]["status"]=="ok"
    assert b["report"]["status"]!=a["report"]["status"]
    assert a["snapshot_digest"]!=b["snapshot_digest"]
    assert get(marker)=={"database_ready":False,"failed_jobs":99}
    assert os.environ["DATABASE_URL"]=="sqlite:///never-use-parent-snapshot.db"
    assert not os.path.exists("never-use-parent-snapshot.db")

def test_worker_environment_allowlist(monkeypatch,tmp_path):
    for key in ("DATABASE_URL","LINE_CHANNEL_ACCESS_TOKEN","OPENAI_API_KEY","FINMIND_TOKEN","GITHUB_TOKEN"):
        monkeypatch.setenv(key,"synthetic")
    env=api.worker_env(str(tmp_path))
    assert env["DATABASE_URL"]=="sqlite:///:memory:"
    assert env["PYTHON_DOTENV_DISABLED"]=="1"
    assert all(k not in env for k in ("LINE_CHANNEL_ACCESS_TOKEN","OPENAI_API_KEY","FINMIND_TOKEN","GITHUB_TOKEN"))

def test_parallel_snapshots_do_not_mix():
    from concurrent.futures import ThreadPoolExecutor
    inputs=[{"database_ready":True,"failed_jobs":0,"stale_jobs":0},{"database_ready":False,"failed_jobs":3,"stale_jobs":2}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda p:api.invoke("system_monitor",p),inputs))
    for p,r in zip(inputs,results):
        assert r["snapshot_digest"]==hashlib.sha256(("system_monitor:"+json.dumps(p,sort_keys=True,separators=(",",":"))).encode()).hexdigest()
        assert r["execution_allowed"] is False
    assert results[0]["report"]["status"]=="ok"
    assert results[1]["report"]["status"]!="ok"


@pytest.mark.parametrize("name",["data_auditor","notification","recovery","research","risk"])
def test_other_worker_matches_parent_supervisor(name):
    from datetime import datetime,timedelta
    from zoneinfo import ZoneInfo
    from copy import deepcopy
    from app.agents.supervisor import Supervisor
    from app.services.trading_calendar import expected_close
    from test_agent_risk import position
    now=datetime.now(ZoneInfo("Asia/Taipei"))
    docs={f"recommendations:calendar:{y}":{"year":y,"closed":[],"opened":[]} for y in (now.year-1,now.year)}
    day=now.date()-timedelta(days=1)
    while day.weekday()>=5:
        day-=timedelta(days=1)
    docs[f"recommendations:outbox:{day}:morning:fixture"]={"messages":[{"retry_key":"same"},{"retry_key":"same"}]}
    pos=deepcopy(position())
    pos["research"]["documents"]=docs
    pos["research"]["quote"]["date"]=str(expected_close(now,docs.get))
    payloads={
        "data_auditor":{"symbols":["2330.TW"],"documents":docs},
        "notification":{"users":["fixture"],"documents":docs,"days":7},
        "recovery":{"monitor":{"mode":"shadow","status":"attention","checks":[{"code":"database","severity":"critical"}]}},
        "research":pos["research"],
        "risk":{"positions":[pos],"cash":1000},
    }
    payload=payloads[name]
    original=deepcopy(payload)
    result=api.invoke(name,payload)
    actual=result["report"]
    assert actual["mode"]=="shadow"
    assert actual["status"] not in ("unknown","denied","error","timeout")
    assert result["execution_allowed"] is False
    assert payload==original
    canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False)
    assert result["snapshot_digest"]==hashlib.sha256((name+":"+canonical).encode()).hexdigest()
    # Use worker completion time for the parent reference. Compare stable
    # business fields rather than wall-clock-derived evidence versions.
    observed=datetime.fromisoformat(result["observed_at"])
    sup=Supervisor(enabled=True)
    if name=="data_auditor":
        expected=sup.audit_data(**payload,now=observed,is_admin=True)
        fields=("status","rows","repair_priority")
    elif name=="notification":
        expected=sup.audit_notifications(now=observed,read=docs.get,users=payload["users"],days=7,is_admin=True)
        fields=("status","history")
    elif name=="recovery":
        expected=sup.plan_recovery(monitor=payload["monitor"],data=None,notification=None,now=observed,is_admin=True)
        fields=("status","plans","executed")
        assert actual["executed"] is False
    elif name=="research":
        expected=sup.research(**payload,now=observed,is_admin=True)
        fields=("status","confidence","input_digest","execution_allowed")
    else:
        expected=sup.risk(**payload,now=observed,is_admin=True)
        fields=("status","weights","stress_returns","risk_grade","execution_allowed")
    expected=json.loads(json.dumps(expected,allow_nan=False))
    for field in fields:
        assert field in expected and field in actual
        assert actual[field]==expected[field],field
