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
