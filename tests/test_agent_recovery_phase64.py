from datetime import datetime,timezone,timedelta
from app.agents.recovery_state import RecoverySimulation,verify_pair
from app.agents.system_monitor import SystemMonitor
from app.agents.contracts import Snapshot
from test_agent_recovery_phase63 import plan,NOW

def test_required_id():
    s=RecoverySimulation();k=plan(s)["plans"][0]["id"]
    assert not s.transition(k,"approve",NOW)
    assert s.transition(k,"approve",NOW,operation_id="a")

def test_reopen_and_renew():
    s=RecoverySimulation();k=plan(s)["plans"][0]["id"]
    assert s.transition(k,"approve",NOW,operation_id="a")
    for i in range(3):assert s.transition(k,"simulate_failure",NOW,operation_id=str(i))
    later=NOW+timedelta(minutes=16)
    plan(s,later)
    assert s.transition(k,"approve",later,operation_id="renew")
    assert s.transition(k,"simulate_probe",later,operation_id="probe")
    assert s.transition(k,"simulate_probe_failure",later,operation_id="failed")
    p=next(p for p in plan(s,later)["plans"] if p["id"]==k)
    assert p["circuit"]=="open"
    assert not s.transition(k,"simulate_probe",later,operation_id="again")
    events=next(e["events"] for e in s.export_history()["events"] if e["plan"]==k)
    assert len(events)==7 and all(len(e["operation"])==64 for e in events)

def test_dependency():
    s=RecoverySimulation()
    e={"monitor":{"source":"monitor","at":NOW,"report":{"mode":"shadow","checks":[{"code":"api_ready","severity":"critical"}]}},"notification":{"source":"notification","at":NOW,"report":{"mode":"shadow","history":[{"counts":{"partial":1}}]}}}
    r=s.plan(incident="a",now=NOW,evidence=e)
    p=next(p for p in r["plans"] if p["source"]=="notification")
    assert p["blocked_by_dependency"] and p["action"]=="hold_and_review"
    assert s.transition(p["id"],"approve",NOW,operation_id="a")
    assert not s.transition(p["id"],"simulate_failure",NOW,operation_id="b")

def test_independent_fixture_samples():
    # Two separately read local fixture snapshots, never a live collector.
    from tempfile import TemporaryDirectory
    from pathlib import Path
    import json
    from hashlib import sha256
    with TemporaryDirectory() as d:
        def sample(name,state,at):
            p=Path(d)/name
            p.write_text(json.dumps({"state":state,"sample":name}))
            raw=p.read_bytes()
            return {"collector":"monitor","incident":"fixture","sample_id":sha256(raw).hexdigest(),"state":json.loads(raw)["state"],"at":at}
        b=sample("before","critical",NOW-timedelta(seconds=1))
        a=sample("after","ok",NOW)
        assert verify_pair(b,a,NOW)=="simulated_improvement"
