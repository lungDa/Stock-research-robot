from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock
from app.agents.monitor_policy import due_slots, coverage, expected_receipts
from app.agents.monitor_worker_v2 import workflow_state
from app.agents import monitor_v2
from app.agents.monitor_probe import receipt_state

NOW=datetime(2026,11,26,21,0,tzinfo=ZoneInfo("Asia/Taipei"))
def read(key, default=None):
    if key=="recommendations:session_overrides":
        return {"2026-11-26":True}
    return default

def test_due_slots():
    slots=due_slots(NOW,read,[(11,30),(19,30)])
    assert len(slots)==2
    assert workflow_state([],slots,NOW)=="warning"
    assert due_slots(NOW,lambda k,d:d,[(11,30)]) is None

def test_coverage_not_verified():
    assert coverage({"known_items":10,"expected_items":10,"at":NOW.timestamp()},NOW)==("unknown",100)
    assert coverage({"known_items":5,"expected_items":10,"at":NOW.timestamp()},NOW)==("warning",50)

def test_missing_expected_receipt():
    def prefs(k,d=None):
        return {"enabled":True} if k=="recommendations:preferences:u" else read(k,d)
    assert expected_receipts(NOW,prefs,["u"],receipt_state)=="warning"

def test_disabled_no_process(monkeypatch):
    run=Mock()
    monkeypatch.setattr(monitor_v2.subprocess,"run",run)
    assert monitor_v2.collect()["status"]=="denied"
    run.assert_not_called()

def test_independent_results(monkeypatch):
    def run(args,**kwargs):
        if args[-1]=="api_health":
            raise OSError("secret")
        return Mock(stdout='{"state":"ok"}')
    monkeypatch.setattr(monitor_v2.subprocess,"run",run)
    result=monitor_v2.collect(enabled=True,is_admin=True)
    assert result["status"]=="unknown"
    assert len(result["checks"])==10
    assert "secret" not in str(result)
