from datetime import datetime,timezone
from app.agents.recovery import RecoveryAgent,retry_policy,verify_simulation
from app.agents.supervisor import Supervisor
from app.agents.registry import Registry
NOW=datetime(2026,11,26,tzinfo=timezone.utc)
def inputs():
    return dict(now=NOW,monitor={"mode":"shadow","checks":[{"code":"database","severity":"critical"}]},data={"mode":"shadow","rows":[{"expected_items":31,"complete_items":10,"conflicts":["private"]}]},notification={"mode":"shadow","history":[{"counts":{"api_accepted_only":1,"partial":1}}],"duplicate_retry_keys":1})
def test_denied():
    assert Supervisor().plan_recovery(**inputs(),is_admin=True)["status"]=="denied"
def test_registry():
    assert isinstance(Registry().resolve("recovery"),RecoveryAgent)
def test_integrated():
    r=Supervisor(enabled=True).plan_recovery(**inputs(),is_admin=True)
    assert r["status"]=="planned" and not r["executed"]
    assert {p["source"] for p in r["plans"]}=={"monitor","data","notification"}
    assert r["plans"][0]["severity"]=="critical"
    assert all(not p["execution_allowed"] and p["approval_required"] for p in r["plans"])
    assert "private" not in str(r)
    assert any(p["action"]=="do_not_resend" for p in r["plans"])
def test_stable_keys():
    a=RecoveryAgent().plan(**inputs())
    b=RecoveryAgent().plan(**inputs())
    assert a==b
def test_circuit():
    assert retry_policy(0,0)["delay_seconds"]==30
    assert retry_policy(2,2)["delay_seconds"]==120
    assert retry_policy(3,0)["state"]=="open"
    assert retry_policy(0,3)["state"]=="open"
def test_unknown():
    r=RecoveryAgent().plan(now=NOW,monitor=None,data=None,notification=None)
    assert len(r["plans"])==3 and all(p["action"]=="collect_evidence" for p in r["plans"])
def test_verify():
    assert verify_simulation({"execution_allowed":False},before="critical",after="ok")=="simulated_improvement"
    assert verify_simulation({"execution_allowed":False},before="critical",after="unknown")=="not_verified"
def test_no_admin():
    assert Supervisor(enabled=True).plan_recovery(**inputs(),is_admin=False)["status"]=="denied"
