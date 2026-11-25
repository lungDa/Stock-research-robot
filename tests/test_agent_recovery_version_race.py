from concurrent.futures import ThreadPoolExecutor
from threading import Event
from app.agents.recovery_state import RecoverySimulation
from test_agent_recovery_state import NOW,evidence

def test_stale_approval_race():
    s=RecoverySimulation()
    p=s.plan(incident="a",now=NOW,evidence=evidence())["plans"][0]
    ready=Event()
    def approve():
        assert ready.wait(5)
        return s.transition(p["id"],"approve",NOW,operation_id="a",expected_version=p["evidence_version"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(approve)
        e=evidence()
        e["monitor"]["report"]["checks"].append({"code":"api_ready","severity":"critical"})
        q=next(x for x in s.plan(incident="a",now=NOW,evidence=e)["plans"] if x["id"]==p["id"])
        ready.set()
        assert not future.result(timeout=5)
    assert not s.transition(p["id"],"approve",NOW,operation_id="missing")
    assert s.transition(p["id"],"approve",NOW,operation_id="a",expected_version=q["evidence_version"])

def test_outbox_content_changes_version():
    s=RecoverySimulation()
    o={"incident":"a","at":NOW,"key":"private-key","document":{"messages":[{"retry_key":"private","text":"secret-one","sent":True,"acceptance":{"http_status":200,"request_id":"x"}}]}}
    p=s.plan(incident="a",now=NOW,evidence=evidence(),outbox=o)["plans"][0]
    assert s.transition(p["id"],"approve",NOW,operation_id="a",expected_version=p["evidence_version"])
    o["document"]["messages"][0]["text"]="secret-two"
    r=s.plan(incident="a",now=NOW,evidence=evidence(),outbox=o)
    q=next(x for x in r["plans"] if x["id"]==p["id"])
    assert q["evidence_version"]!=p["evidence_version"]
    assert q["approval_state"]=="pending"
    assert "secret" not in str(r) and "secret" not in str(s.export_history())
