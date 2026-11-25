from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
from app.agents.recovery_state import RecoverySimulation
NOW=datetime(2026,11,26,tzinfo=timezone.utc)
def plan(s,now=NOW):
    return s.plan(incident="test",now=now,evidence={"monitor":{"source":"monitor","at":now,"report":{"mode":"shadow","checks":[{"code":"database","severity":"critical"}]}}})
def test_concurrent_idempotency():
    s=RecoverySimulation();k=plan(s)["plans"][0]["id"]
    assert s.transition(k,"approve",NOW)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:s.transition(k,"simulate_failure",NOW,operation_id="same"),range(20)))
    assert sum(results)==1
    assert s.export_history()["executed"] is False
def test_probe_success():
    s=RecoverySimulation();k=plan(s)["plans"][0]["id"]
    assert s.transition(k,"approve",NOW)
    for i in range(3):assert s.transition(k,"simulate_failure",NOW,operation_id=str(i))
    later=NOW+timedelta(minutes=15)
    assert s.transition(k,"simulate_probe",later)
    assert s.transition(k,"simulate_probe_success",later)
    p=next(p for p in plan(s,later)["plans"] if p["id"]==k)
    assert p["circuit"]=="closed"
def test_expired_approval():
    s=RecoverySimulation();k=plan(s)["plans"][0]["id"]
    assert s.transition(k,"approve",NOW)
    assert not s.transition(k,"simulate_failure",NOW+timedelta(minutes=16))
def test_outbox():
    s=RecoverySimulation()
    r=s.plan(incident="test",now=NOW,evidence={},outbox={"incident":"test","at":NOW,"key":"private-key","document":{"messages":[{"retry_key":"private","sent":True,"acceptance":{"http_status":200,"request_id":"x"}}]}})
    assert r["outbox_review"]["advice"]=="do_not_resend"
    assert "private" not in str(r)
