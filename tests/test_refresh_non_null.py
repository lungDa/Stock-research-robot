"""Guard against silent no-op refresh workers."""
import subprocess
from contextlib import contextmanager
from unittest.mock import patch
from jobs import refresh_data, refresh_step

@contextmanager
def owned(*args, **kwargs):
    yield True

def test_null_worker_result_is_not_success():
    with patch.object(refresh_data, "STEPS", ["annual"]), \
         patch.object(refresh_data, "init_db"), \
         patch.object(refresh_data, "put"), \
         patch.object(refresh_data, "leased", owned), \
         patch.object(refresh_data.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="null\n", stderr="")):
        result = refresh_data.run()
    assert result["state"] == "partial"
    assert result["steps"]["annual"]["state"] == "partial"

def test_refresh_step_invokes_actual_worker():
    with patch("jobs.refresh_annual.run", return_value={"annual_requests": 1, "updated_symbols": 1, "failed_feeds": 0}) as worker:
        result = refresh_step.run("annual")
    worker.assert_called_once_with(max_requests=2, seconds=18)
    assert result["updated_symbols"] == 1
