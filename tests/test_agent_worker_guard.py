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

def test_worker_guard_denies_private_file_reads(tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("SYNTHETIC_SECRET")
    alias = tmp_path / "alias.txt"
    alias.symlink_to(secret)
    for path in (secret, alias):
        code = ("from app.agents.worker_guard import install; install()\n"
                "try:\n open(" + repr(str(path)) + ").read()\n"
                "except PermissionError:\n raise SystemExit(0)\n"
                "raise SystemExit(1)")
        result = subprocess.run([sys.executable, "-c", code],
                                capture_output=True, timeout=10)
        assert result.returncode == 0
        assert b"SYNTHETIC_SECRET" not in result.stdout + result.stderr
