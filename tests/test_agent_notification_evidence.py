from datetime import datetime,timezone
from app.agents.notification_evidence import duplicate_keys,workflow_history,signal_summary
from app.agents.notification import inspect_outbox
from app.agents.supervisor import Supervisor
from app.db import put,get,engine
NOW=datetime(2026,11,26,12,tzinfo=timezone.utc)
def test_cross_outbox():
    d={"messages":[{"retry_key":"secret"}]}
    assert duplicate_keys([d,d])==1
def test_partial_and_cross_day():
    d={"created_at":NOW.timestamp()-60,"messages":[{"retry_key":"a","sent":True,"acceptance":{"http_status":200,"request_id":"id"}},{"retry_key":"b","sent":False}]}
    assert inspect_outbox(d,NOW,True)[0]=="partial"
    assert inspect_outbox(d,NOW,False)[0]=="expired_or_unknown"
def test_workflow_failure_not_masked():
    runs=[{"head_branch":"main","event":"schedule","created_at":"2026-11-26T10:17:00Z","status":"completed","conclusion":s} for s in ("failure","success")]
    assert workflow_history(runs,NOW.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Taipei")),1,18,17)[0]["state"]=="failed"
def test_signal_unknown():
    assert signal_summary([{"pending":{"blocked":True}}],NOW)=={"blocked_unknown_reason":1}
def test_db_denied(monkeypatch):
    monkeypatch.delenv("AGENT_NOTIFICATION_DB_READ",raising=False)
    assert Supervisor(enabled=True).audit_notification_database(now=NOW,is_admin=True)["status"]=="denied"
def test_isolated_read(monkeypatch):
    assert engine.dialect.name=="sqlite"
    monkeypatch.setenv("AGENT_NOTIFICATION_DB_READ","1")
    monkeypatch.delenv("AGENT_NOTIFICATION_GITHUB_READ",raising=False)
    d={"messages":[{"retry_key":"private"}]}
    put("recommendations:outbox:2026-11-26:morning:Ualice",d)
    put("four_rankings:outbox:2026-11-26:morning:Ualice",d)
    r=Supervisor(enabled=True).audit_notification_database(now=NOW,days=1,is_admin=True)
    assert r["status"]=="complete"
    assert r["duplicate_retry_keys"]==1
    assert "private" not in str(r)
    assert get("recommendations:outbox:2026-11-26:morning:Ualice")==d
