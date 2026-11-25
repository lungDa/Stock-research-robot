"""Single check per subprocess; no writes, no provider refresh."""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from app.agents import monitor_probe as old
from app.agents.monitor_policy import due_slots, coverage, expected_receipts

ORIGIN = "https://stock-lighthouse-api.onrender.com"
TIMES = {"ranking_workflow": [(11,30),(19,30)], "scan_workflow": [(18,17)], "refresh_workflow": [(6,0),(12,0),(18,0),(23,0)]}

def workflow_state(runs, due, now):
    if not due:
        return "unknown"
    # Require evidence for each due slot; later runs cannot mask earlier failures.
    for i, slot in enumerate(due):
        end = due[i+1] if i+1<len(due) else now
        matches = []
        for r in runs:
            try:
                at = datetime.fromisoformat(r["created_at"].replace("Z","+00:00"))
                if slot <= at < end and r.get("event") in ("schedule","workflow_run"):
                    matches.append((at,r))
            except (ValueError,TypeError,KeyError,AttributeError):
                continue
        if not matches:
            return "warning"
        latest = max(matches,key=lambda x:x[0])[1]
        if latest.get("status")!="completed":
            return "warning"
        if latest.get("conclusion") in ("failure","timed_out","cancelled"):
            return "critical"
        if latest.get("conclusion")!="success":
            return "unknown"
    return "ok"

def run(code):
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    if code.startswith("api_"):
        if os.getenv("AGENT_MONITOR_API_URL","").rstrip("/") != ORIGIN:
            return {"state":"unknown"}
        path = {"api_health":"/health","api_ready":"/ready","api_version":"/version"}[code]
        try:
            data = old.read_json(ORIGIN+path)
            valid = bool(data.get("version")) and isinstance(data.get("version"),str) if code=="api_version" else data.get("status")=="ok"
            if code=="api_ready":
                valid = valid and data.get("database")=="ok"
            return {"state":"ok" if valid else "unknown"}
        except old.HTTPError as e:
            return {"state":"critical" if e.code>=500 else "unknown"}
    if os.getenv("AGENT_MONITOR_DB_READ")!="1":
        return {"state":"unknown"}
    from app.db import Session, Document
    from sqlalchemy import text, select
    from app.config import settings
    with Session() as s:
        if s.bind.dialect.name=="postgresql":
            s.execute(text("SET TRANSACTION READ ONLY"))
            s.execute(text("SET LOCAL statement_timeout = '4000ms'"))
        elif s.bind.dialect.name!="sqlite":
            return {"state":"unknown"}
        def read(key, default=None):
            row=s.get(Document,key)
            return json.loads(row.payload) if row else default
        if code=="database":
            s.execute(text("SELECT 1"))
            return {"state":"ok"}
        if code=="financial_refresh":
            return {"state":old.financial_state(read("jobs:data_refresh",{}))}
        if code=="financial_coverage":
            state,pct=coverage(read("v27:coverage:six_factor_provisional",{}),now)
            return {"state":state,"coverage_pct":pct}
        if code=="line_receipts":
            rows=list(s.scalars(select(Document).where(Document.key.startswith("member:",autoescape=True)).limit(101)))
            if len(rows)>100:
                return {"state":"unknown"}
            accounts={r.key[7:]:json.loads(r.payload) for r in rows}
            users=set(settings.users.values())|set(accounts)
            if len(users)>100:
                return {"state":"unknown"}
            users=[u for u in users if accounts.get(u,{"active":True}).get("active") and not accounts.get(u,{}).get("password_change_required",False)]
            return {"state":expected_receipts(now,read,users,old.receipt_state)}
        if code in TIMES:
            due=due_slots(now,read,TIMES[code],trading=code!="refresh_workflow")
        else:
            return {"state":"unknown"}
    if due is None:
        return {"state":"unknown"}
    runs=old.read_json(old.GITHUB+old.WORKFLOWS[code]+"/runs?branch=main&per_page=100")["workflow_runs"]
    return {"state":workflow_state(runs,due,now)}

if __name__=="__main__":
    try:
        print(json.dumps(run(sys.argv[1])))
    except Exception:
        print('{"state":"unknown"}')
