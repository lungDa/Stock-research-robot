import sys,time,subprocess
from datetime import datetime,timezone
import pytest
from app.agents.notification_policy import paged,isolated_evidence
from app.agents import notification_process as process
NOW=datetime(2026,11,26,12,tzinfo=timezone.utc)
def test_real_blocked_child(monkeypatch):
    monkeypatch.setenv("AGENT_NOTIFICATION_DB_READ","1")
    original=process._run_child
    monkeypatch.setattr(process,"_run_child",lambda command,timeout:original([sys.executable,"-c","import time; time.sleep(30)"],timeout))
    start=time.monotonic()
    assert process.collect(now=NOW,timeout=0.5)["status"]=="timeout"
    assert time.monotonic()-start<10
def test_run_pages():
    rows,complete=paged(lambda p:{"total_count":2,"workflow_runs":[{"id":p}]},collection="workflow_runs")
    assert complete and len(rows)==2
    assert not paged(lambda p:{"total_count":6,"workflow_runs":[{"id":p}]},collection="workflow_runs",max_pages=5)[1]
def test_evidence_integration():
    snapshot={"version":1,"date":"2026-11-26","slot":"evening","report":"recommendations","complete":True,"eligible_users":["private-user"]}
    doc={"created_at":NOW.timestamp()-60,"messages":[{"retry_key":"private-key","sent":False}]}
    args=dict(snapshot=snapshot,day=NOW.date(),slot="evening",report="recommendations",user="private-user",event="schedule",cron="30 11 * * 1-5",error={"version":1,"http_status":429},outbox=doc,now=NOW)
    result=isolated_evidence(**args)
    assert result=={"mode":"shadow","eligible":True,"trigger":"evening","error":"rate_limited","advice":"hold_and_review"}
    assert "private" not in str(result)
    args["snapshot"]=None
    args["error"]=None
    assert isolated_evidence(**args)["advice"]=="manual_review"
