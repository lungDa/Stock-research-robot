from datetime import datetime,timezone
import subprocess
from app.agents.notification_policy import subscription_snapshot,cron_evidence,error_evidence,recovery_advice,paged
from app.agents.notification_process import collect
from app.agents.supervisor import Supervisor
NOW=datetime(2026,11,26,12,tzinfo=timezone.utc)
def test_snapshot():
    d={"version":1,"date":"2026-11-26","slot":"morning","report":"recommendations","complete":True,"eligible_users":["private"]}
    assert subscription_snapshot(d,NOW.date(),"morning","recommendations")=={"private"}
    assert subscription_snapshot(d,NOW.date(),"evening","recommendations") is None
def test_cron():
    assert cron_evidence("schedule","7,37 4-15 * * 1-5")=="compensation"
    assert cron_evidence("schedule")=="unknown_schedule"
def test_errors():
    assert error_evidence({"version":1,"http_status":429})=="rate_limited"
    assert error_evidence({"version":1,"reason":"quota_exhausted"})=="quota_exhausted"
    assert error_evidence({"http_status":429})=="unknown"
def test_recovery():
    d={"created_at":NOW.timestamp()-10,"messages":[{"retry_key":"a","sent":False}]}
    assert recovery_advice(d,NOW,same_day=True)=="manual_review"
    assert recovery_advice(d,NOW,same_day=True,eligible=True)=="review_existing_retry_keys"
    assert recovery_advice(d,NOW,same_day=True,eligible=True,error="rate_limited")=="hold_and_review"
    assert recovery_advice(d,NOW,same_day=False,eligible=True)=="manual_review"
def test_pages():
    assert paged(lambda p:{"total_count":2,"jobs":[{"id":p}]})[1]
    assert not paged(lambda p:{"total_count":2,"jobs":[{"id":1}]})[1]
def test_hard_timeout(monkeypatch):
    monkeypatch.setenv("AGENT_NOTIFICATION_DB_READ","1")
    def timeout(*args,**kwargs):raise subprocess.TimeoutExpired(args[0],kwargs["timeout"])
    monkeypatch.setattr(subprocess,"run",timeout)
    assert collect(now=NOW,timeout=1)["status"]=="timeout"
def test_denied():
    assert Supervisor().audit_notification_isolated(now=NOW,is_admin=True)["status"]=="denied"
