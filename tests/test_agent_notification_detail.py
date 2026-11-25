from datetime import datetime,timezone
from app.agents.notification_detail import trigger,job_evidence,digest_evidence,quota_evidence,pending_keys
from app.agents.notification_evidence import duplicate_keys
def test_manual_not_delivery():
    r=job_evidence({"event":"workflow_dispatch"},[{"steps":[{"name":"Send daily watchlist report","conclusion":"skipped"}]}])
    assert r["trigger"]=="manual_preview_or_send"
    assert r["steps"]=={"watch_digest:skipped":1}
    assert r["delivery_verified"] is False
def test_compensation_unknown():
    assert trigger({"event":"schedule"})=="scheduled_primary_or_compensation"
def test_quota_evidence():
    assert quota_evidence([{"status":"quota_exhausted"}])=={"quota_exhausted":1}
    assert quota_evidence([{"pending":{"blocked":True}}])=={"unknown":1}
    assert quota_evidence([{"messages":[{"acceptance":{"http_status":429}}]}])=={"http_429":1}
def test_cross_type():
    assert duplicate_keys([{"messages":[{"retry_key":"a"}]}]+pending_keys([{"pending":{"retry_key":"a"}}]))==1
def test_digest_receipt():
    now=datetime(2026,11,26,12,tzinfo=timezone.utc)
    d={"messages":[{"retry_key":"a","sent":True,"acceptance":{"http_status":200,"request_id":"x"}}]}
    assert digest_evidence({"watch_digest:outbox:2026-11-26:private":d},now)=={"api_accepted_only":1}
def test_deadline(monkeypatch):
    from app.agents import notification_evidence as e
    monkeypatch.setenv("AGENT_NOTIFICATION_DB_READ","1")
    monkeypatch.setattr(e.time,"monotonic",iter([0,31]).__next__)
    assert e.read_notifications(now=datetime(2026,11,26,12,tzinfo=timezone.utc))["status"]=="unknown"
