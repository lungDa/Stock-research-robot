from app.agents.recovery_state import RecoverySimulation
from test_agent_recovery_state import evidence,NOW

def test_changed_evidence_revokes_approval():
    s=RecoverySimulation()
    e=evidence()
    p=s.plan(incident="a",now=NOW,evidence=e)["plans"][0]
    k=p["id"]
    assert s.transition(k,"approve",NOW,operation_id="a")
    e["monitor"]["report"]["checks"].append({"code":"api_ready","severity":"critical"})
    q=next(p for p in s.plan(incident="a",now=NOW,evidence=e)["plans"] if p["id"]==k)
    assert q["evidence_version"]!=p["evidence_version"]
    assert q["approval_state"]=="pending"
    assert not s.transition(k,"simulate_failure",NOW,operation_id="b")
    assert s.transition(k,"approve",NOW,operation_id="c")
    assert s.transition(k,"simulate_failure",NOW,operation_id="d")
    events=next(e["events"] for e in s.export_history()["events"] if e["plan"]==k)
    assert events[-1]["evidence_version"]==q["evidence_version"]

def test_same_evidence_preserves_approval():
    s=RecoverySimulation()
    p=s.plan(incident="a",now=NOW,evidence=evidence())["plans"][0]
    assert s.transition(p["id"],"approve",NOW,operation_id="a")
    q=s.plan(incident="a",now=NOW,evidence=evidence())["plans"][0]
    assert q["evidence_version"]==p["evidence_version"]
    assert q["approval_state"]=="approved"
