"""Independent, bounded shadow checks; fixed output schema."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from app.agents.live_monitor import ADVICE, STATES

CODES = ("api_health","api_ready","api_version","database","ranking_workflow","scan_workflow","refresh_workflow","financial_refresh","financial_coverage","line_receipts")

def collect(*, enabled=False, is_admin=False, timeout=15):
    if enabled is not True or is_admin is not True:
        return {"mode":"shadow","status":"denied","checks":[]}
    if type(timeout) is not int or not 1 <= timeout <= 30:
        raise ValueError("invalid timeout")
    def one(code):
        state, pct = "unknown", None
        try:
            p = subprocess.run([sys.executable,"-m","app.agents.monitor_worker_v2",code],capture_output=True,text=True,check=True,timeout=timeout)
            data = json.loads(p.stdout)
            value = data.get("state")
            if isinstance(value,str) and value in STATES:
                state = value
            value = data.get("coverage_pct")
            if code=="financial_coverage" and type(value) in (int,float) and 0<=value<=100:
                pct = value
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
            pass
        result = {"code":code,"severity":state,"advice":ADVICE[state]}
        if pct is not None:
            result.update(coverage_pct=pct,scope="six_factor_provisional_sample")
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(one,CODES))
    status = next(s for s in ("critical","warning","unknown","ok") if any(c["severity"]==s for c in checks))
    return {"mode":"shadow","status":status,"checks":checks}
