from datetime import timedelta
from app.agents.recovery_state import RecoverySimulation
from test_agent_recovery_phase63 import NOW,plan

def test_old_evidence_not_extended():
    s=RecoverySimulation()
    k=plan(s)["plans"][0]["id"]
    e={"monitor":{"source":"monitor","at":NOW,"report":{"mode":"shadow","checks":[{"code":"database","severity":"critical"}]}}}
    s.plan(incident="test",now=NOW+timedelta(minutes=14),evidence=e)
    assert not s.transition(k,"approve",NOW+timedelta(minutes=16),operation_id="late")

def test_disappeared_incident_blocked():
    s=RecoverySimulation()
    k=plan(s)["plans"][0]["id"]
    assert s.transition(k,"approve",NOW,operation_id="a",expected_version=s._states[k]["version"])
    s.plan(incident="test",now=NOW,evidence={"monitor":{"source":"monitor","at":NOW,"report":{"mode":"shadow","checks":[{"code":"database","severity":"ok"}]}}})
    assert not s.transition(k,"simulate_failure",NOW,operation_id="b")
