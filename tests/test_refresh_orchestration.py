"""Regression checks for bounded refresh orchestration."""
import json
import subprocess
from unittest.mock import patch
from jobs import refresh_data

def test_step_timeout_is_recorded_and_later_steps_continue():
    with patch.object(refresh_data, "STEPS", ["one", "two"]), \
         patch.object(refresh_data, "STEP_TIMEOUT", 1), \
         patch.object(refresh_data, "init_db"), \
         patch.object(refresh_data, "put") as put, \
         patch.object(refresh_data, "leased") as leased, \
         patch.object(refresh_data.subprocess, "run", side_effect=[
             subprocess.TimeoutExpired("one", 1),
             subprocess.CompletedProcess([], 0, stdout='{"state":"finished"}\n', stderr=""),
         ]):
        from contextlib import contextmanager
        @contextmanager
        def owned(*args, **kwargs):
            yield True
        leased.side_effect = owned
        result = refresh_data.run()
    assert result["state"] == "partial"
    assert result["steps"]["one"]["state"] == "timeout"
    assert result["steps"]["two"]["state"] == "finished"
    assert put.call_count >= 4

def test_busy_is_not_reported_as_success():
    from contextlib import contextmanager
    @contextmanager
    def not_owned(*args, **kwargs):
        yield False
    with patch.object(refresh_data, "init_db"), patch.object(refresh_data, "leased", not_owned):
        assert refresh_data.run()["state"] == "busy"


def test_summary_exception_does_not_interrupt_later_steps():
    from contextlib import nullcontext
    with patch.object(refresh_data, "STEPS", ["tw_financials", "paid"]), \
         patch.object(refresh_data, "init_db"), \
         patch.object(refresh_data, "put"), \
         patch.object(refresh_data, "leased", return_value=nullcontext(True)), \
         patch("jobs.tw_financial_summary.write_summary", side_effect=RuntimeError("summary")), \
         patch.object(refresh_data.subprocess, "run", side_effect=[
             subprocess.CompletedProcess([], 0, stdout='{"state":"partial","failed_feeds":1}', stderr=""),
             subprocess.CompletedProcess([], 0, stdout='{"state":"finished"}', stderr=""),
         ]):
        result = refresh_data.run()
    assert result["state"] == "partial"
    assert result["steps"]["tw_financials"]["state"] == "partial"
    assert result["steps"]["paid"]["state"] == "finished"
