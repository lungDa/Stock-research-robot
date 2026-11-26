import json
import subprocess
from unittest.mock import Mock
from app.agents import live_monitor as m
from app.agents import monitor_probe as p

def test_disabled(monkeypatch):
    run = Mock()
    monkeypatch.setattr(m.subprocess, "run", run)
    assert m.collect()["status"] == "denied"
    run.assert_not_called()

def test_timeout_and_redaction(monkeypatch):
    run = Mock(side_effect=[subprocess.TimeoutExpired("secret", 1), Mock(stdout=json.dumps({"ranking_workflow":"critical","scan_workflow":"token-secret"})), Mock(stdout="bad")])
    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.collect(enabled=True, is_admin=True, timeout=1)
    assert result["status"] == "critical"
    assert len(result["checks"]) == 9
    assert "secret" not in str(result)
    assert run.call_count == 3

def test_receipt():
    assert p.receipt_state({}) == "unknown"
    assert p.receipt_state({"messages":[{"sent":False}]}) == "warning"
    assert p.receipt_state({"messages":[{"sent":True}]}) == "unknown"
    assert p.receipt_state({"messages":[{"sent":True,"acceptance":{"delivery_status":"api_accepted_only","http_status":200,"request_id":"secret"}}]}) == "ok"

def test_financial_unknown():
    assert p.financial_state({}) == "unknown"

def test_db_disabled(monkeypatch):
    monkeypatch.delenv("AGENT_MONITOR_DB_READ", raising=False)
    assert p.database() == {}

def test_api_unconfigured(monkeypatch):
    monkeypatch.delenv("AGENT_MONITOR_API_URL", raising=False)
    assert p.api() == {}
