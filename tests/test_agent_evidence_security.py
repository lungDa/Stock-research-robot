"""Synthetic evidence provenance and boundary tests."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import pytest
from app.api import agent_manager as m
from app.agents.manager_review import ReviewStore,safe_report
from test_agent_api_isolation import client,A,C,PREFIX,PAYLOAD

def test_forged_and_cross_session_evidence(client):
    forged={"mode":"shadow","observed_at":datetime.now(timezone.utc).isoformat(),"checks":[{"code":"database","severity":"critical"}]}
    def recover(report,headers=A):
        return client.post(PREFIX+"/run/recovery",headers=headers,json={"monitor":report}).json()
    assert "review_id" not in recover(forged)
    genuine=client.post(PREFIX+"/run/system_monitor",headers=A,json={**PAYLOAD,"database_ready":False}).json()["report"]
    altered=deepcopy(genuine)
    altered["checks"][0]["severity"]="warning"
    assert "review_id" not in recover(altered)
    assert "review_id" not in recover(genuine,C)
    valid=recover(genuine)
    assert "review_id" in valid
    plan=next(p for p in valid["report"]["plans"] if p["category"]=="system_failure")
    req={"review_id":valid["review_id"],"plan":plan["id"],"version":plan["evidence_version"],"event":"approve","operation_id":"approve"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda _:m.STORE.review("U"+"1"*32,A["Authorization"],req),range(2)))
    assert sorted(outcomes)==[False,True]
    assert client.post(PREFIX+"/review",headers=A,json={**req,"event":"revoke","operation_id":"revoke"}).status_code==200
    assert client.post(PREFIX+"/review",headers=A,json={**req,"operation_id":"replay"}).status_code==409

@pytest.mark.parametrize("name",["../risk","/tmp/risk","risk;echo synthetic","--help"])
def test_invalid_worker_name_never_spawns(monkeypatch,name):
    def forbidden(*a,**k):pytest.fail("unexpected subprocess")
    monkeypatch.setattr(m.subprocess,"run",forbidden)
    assert m.invoke(name,{})["status"]=="unknown"

def test_sensitive_fields_removed():
    report=safe_report({"token":"synthetic_secret","api_key":"synthetic_secret","report":{"text":"synthetic_secret","status":"https://example.invalid/secret"}})
    assert "synthetic_secret" not in str(report)
    assert "example.invalid" not in str(report)

def test_allowed_fields_do_not_accept_arbitrary_secret_strings():
    secret = "synthetic_private_password"
    digest = "a" * 64
    result = safe_report({"status":secret,"code":digest,"symbol":"2330.TW",
                          "snapshot_digest":digest,"mode":"shadow",
                          "observed_at":"2026-11-26T04:00:00+00:00"})
    assert result["status"] == result["code"] == "[redacted]"
    assert result["symbol"] == "2330.TW"
    assert result["snapshot_digest"] == digest
    assert result["mode"] == "shadow"
    assert result["observed_at"] == "2026-11-26T04:00:00+00:00"

def test_refresh_invalidates_review_and_concurrent_revoke(client):
    def monitor():
        return client.post(PREFIX+"/run/system_monitor",headers=A,
                           json={**PAYLOAD,"database_ready":False}).json()["report"]
    def plan(report):
        return client.post(PREFIX+"/run/recovery",headers=A,json={"monitor":report}).json()
    r=plan(monitor())
    p=next(x for x in r["report"]["plans"] if x["category"]=="system_failure")
    req={"review_id":r["review_id"],"plan":p["id"],"version":p["evidence_version"],
         "event":"approve","operation_id":"first"}
    assert client.post(PREFIX+"/review",headers=A,json=req).status_code==200
    def revoke(i):
        return m.STORE.review("U"+"1"*32,A["Authorization"],
                              {**req,"event":"revoke","operation_id":"revoke"+str(i)})
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(revoke,range(2)))==[False,True]
    assert client.post(PREFIX+"/review",headers=A,json={**req,"operation_id":"again"}).status_code==409
    fresh=monitor()
    assert client.post(PREFIX+"/review",headers=A,json={**req,"operation_id":"stale"}).status_code==409
    assert plan(fresh)["review_id"]!=r["review_id"]

def test_approve_revoke_interleaving(client):
    from threading import Barrier
    report=client.post(PREFIX+"/run/system_monitor",headers=A,
                       json={**PAYLOAD,"database_ready":False}).json()["report"]
    r=client.post(PREFIX+"/run/recovery",headers=A,json={"monitor":report}).json()
    p=next(x for x in r["report"]["plans"] if x["category"]=="system_failure")
    req={"review_id":r["review_id"],"plan":p["id"],"version":p["evidence_version"],
         "event":"approve","operation_id":"initial"}
    assert client.post(PREFIX+"/review",headers=A,json=req).status_code==200
    barrier=Barrier(2)
    def transition(event):
        barrier.wait(timeout=5)
        return m.STORE.review("U"+"1"*32,A["Authorization"],
                              {**req,"event":event,"operation_id":"race_"+event})
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(transition,["approve","revoke"]))==[False,True]
    assert client.post(PREFIX+"/review",headers=A,json={**req,"operation_id":"after"}).status_code==409
