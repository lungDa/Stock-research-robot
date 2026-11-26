"""Synthetic side-effect probes; no external services are contacted."""
import subprocess
import sys
import pytest

@pytest.mark.parametrize("probe", [
    "import socket; socket.socket()",
    "import subprocess; subprocess.Popen([sys.executable, '-c', 'pass'])",
    "open('worker-guard-probe', 'w')",
    "import sqlite3; sqlite3.connect('worker-guard-probe.db')",
    "import os; os.mkdir('worker-guard-probe')",
])
def test_worker_guard_denies_side_effects(probe):
    code = ("import sys; from app.agents.worker_guard import install; install(); "
            + "\\ntry:\\n " + probe + "\\nexcept PermissionError:\\n sys.exit(0)\\nsys.exit(1)")
    result = subprocess.run([sys.executable, "-c", code.replace("\\n", "\n")],
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
