"""Bounded, resumable data refresh. Each feed runs in a separate process."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from app.db import init_db, put, leased

STEPS = [
    "maintenance", "universe", "tw_prices", "history", "fundamentals",
    "cash_dividends", "tw_financials", "eps_first", "eps_second",
    "coverage_diagnostic", "annual", "us_prices", "paid",
]
STEP_TIMEOUT = max(15, int(os.getenv("REFRESH_STEP_TIMEOUT_SECONDS", "65")))


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def run():
    init_db()
    # Allow the worker enough time for all bounded steps; a killed worker's
    # lease expires automatically, avoiding permanent lockout.
    with leased("data:scheduled", 1200) as owned:
        if not owned:
            print("Refresh skipped: another worker owns data:scheduled", flush=True)
            return {"state": "busy"}
        result = {"state": "running", "started_at": utcnow(), "steps": {}}
        put("jobs:data_refresh", result)
        for name in STEPS:
            print(f"START {name}", flush=True)
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "jobs.refresh_step", name],
                    capture_output=True, text=True, timeout=STEP_TIMEOUT,
                    check=False,
                )
                if proc.stdout:
                    print(proc.stdout[-6000:], flush=True)
                if proc.stderr:
                    print(proc.stderr[-3000:], file=sys.stderr, flush=True)
                if proc.returncode:
                    entry = {"state": "failed", "exit_code": proc.returncode}
                else:
                    try:
                        value = json.loads(proc.stdout.strip().splitlines()[-1])
                        state = "partial" if isinstance(value, dict) and (
                            value.get("state") in ("failed", "partial", "busy", "limited", "cooldown")
                            or value.get("failed_feeds", 0)
                            or (name == "fundamentals" and isinstance(value, list) and any(
                                isinstance(row, dict) and str(row.get("status", "")).startswith("failed:") for row in value))
                        ) else "finished"
                        entry = {"state": state, "result": value}
                    except (ValueError, IndexError):
                        entry = {"state": "failed", "reason": "missing structured result"}
            except subprocess.TimeoutExpired:
                entry = {"state": "timeout", "timeout_seconds": STEP_TIMEOUT}
                print(f"TIMEOUT {name} after {STEP_TIMEOUT}s", flush=True)
            except Exception as exc:
                entry = {"state": "failed", "reason": type(exc).__name__}
                print(f"FAILED {name}: {type(exc).__name__}", flush=True)
            result["steps"][name] = entry
            result["updated_at"] = utcnow()
            put("jobs:data_refresh", result)
            print(f"END {name}: {entry['state']} ({len(result['steps'])}/{len(STEPS)})", flush=True)
        result["state"] = ("finished" if all(x["state"] == "finished" for x in result["steps"].values()) else "partial")
        result["updated_at"] = utcnow()
        put("jobs:data_refresh", result)
        return result


if __name__ == "__main__":
    outcome = run()
    print(json.dumps(outcome, ensure_ascii=False, default=str), flush=True)
    if outcome["state"] != "finished":
        sys.exit(1)
