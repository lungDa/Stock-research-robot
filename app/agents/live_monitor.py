"""Explicit opt-in, bounded read-only probes. No scheduler or API route."""
import json
import subprocess
import sys

SOURCES = ("api", "github", "database")
CODES = {
    "api": ("api_health", "api_ready", "api_version"),
    "github": ("ranking_workflow", "scan_workflow", "refresh_workflow"),
    "database": ("database", "financial_refresh", "line_receipts"),
}
STATES = {"ok", "warning", "critical", "unknown"}
ADVICE = {
    "ok": "No anomaly in observed evidence.",
    "warning": "Inspect the relevant job or receipt record.",
    "critical": "Investigate service or failed job before recovery.",
    "unknown": "Obtain missing or fresh evidence; do not assume success.",
}

def collect(*, enabled=False, is_admin=False, timeout=15):
    if enabled is not True or is_admin is not True:
        return {"mode": "shadow", "status": "denied", "checks": []}
    if type(timeout) is not int or not 1 <= timeout <= 30:
        raise ValueError("invalid timeout")
    checks = []
    for source in SOURCES:
        data = {}
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "app.agents.monitor_probe", source],
                capture_output=True, timeout=timeout, check=True, text=True,
            )
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                data = parsed
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        for code in CODES[source]:
            state = data.get(code)
            if not isinstance(state, str) or state not in STATES:
                state = "unknown"
            checks.append({"code": code, "severity": state, "advice": ADVICE[state]})
    order = ("critical", "warning", "unknown", "ok")
    status = next(s for s in order if any(c["severity"] == s for c in checks))
    return {"mode": "shadow", "status": status, "checks": checks}
