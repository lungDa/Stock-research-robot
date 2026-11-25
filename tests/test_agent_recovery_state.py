from datetime import datetime,timezone,timedelta
from app.agents.recovery_state import RecoverySimulation,verify_pair
from app.agents.supervisor import Supervisor
NOW=datetime(2026,11,26,tzinfo=timezone.utc)
def evidence():
    return {"monitor":{"source":"monitor","at":NOW,"report":{"mode":"shadow","checks":[{"code":"database","severity":"critical"}]}}}
def test_state():
    s=RecoverySimulation()
    p=s.plan(incident="a",now=NOW,evidence=evidence())["plans"][0]
    k=p["id"]
    assert not s.transition(k,"simulate_failure",NOW,operation_id="denied")
    assert s.transition(k,"approve",NOW,operation_id="approve")
    for i in range(3):assert s.transition(k,"simulate_failure",NOW,operation_id=str(i))
    assert not s.transition(k,"simulate_failure",NOW,operation_id="fourth")
    assert s.transition(k,"simulate_probe",NOW+timedelta(minutes=15),operation_id="probe")
    assert not s.transition(k,"simulate_probe",NOW+timedelta(minutes=15),operation_id="probe")
    assert len(s.history(k))==5
    p=next(p for p in s.plan(incident="a",now=NOW,evidence=evidence())["plans"] if p["id"]==k)
    assert p["circuit"]=="open" and p["action"]=="hold_and_review" and not p["execution_allowed"]
def test_source():
    e=evidence();e["monitor"]["source"]="data"
    r=RecoverySimulation().plan(incident="a",now=NOW,evidence=e)
    assert all(p["category"]=="unknown" for p in r["plans"])
def test_stale():
    r=RecoverySimulation().plan(incident="a",now=NOW+timedelta(minutes=16),evidence=evidence())
    assert all(p["category"]=="unknown" for p in r["plans"])
def test_verify():
    b={"collector":"monitor","sample_id":"1","incident":"a","at":NOW-timedelta(seconds=1),"state":"critical"}
    a={**b,"sample_id":"2","at":NOW,"state":"ok"}
    assert verify_pair(b,a,NOW)=="simulated_improvement"
    assert verify_pair(b,{**a,"sample_id":"1"},NOW)=="unknown"
def test_denied():
    assert Supervisor().recovery_simulation(is_admin=True) is None
