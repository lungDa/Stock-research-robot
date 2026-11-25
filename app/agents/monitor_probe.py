"""Internal worker. Outputs only fixed status codes; never raw payloads."""
import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

GITHUB = "https://api.github.com/repos/lungDa/Stock-research-robot/actions/workflows/"
WORKFLOWS = {"ranking_workflow": "recommendations.yml", "scan_workflow": "daily.yml", "refresh_workflow": "data-refresh.yml"}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def read_json(url):
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "stock-shadow-monitor"})
    with build_opener(NoRedirect()).open(request, timeout=5) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("response too large")
        return json.loads(raw)

def age_hours(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return age if age >= 0 else None
    except (TypeError, ValueError, AttributeError):
        return None

def api():
    from urllib.parse import urlsplit
    base = os.getenv("AGENT_MONITOR_API_URL", "").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or parsed.port not in (None, 443):
        return {}
    # Operator-controlled environment only, never request input.
    out = {}
    for code, path in (("api_health", "/health"), ("api_ready", "/ready"), ("api_version", "/version")):
        try:
            value = read_json(base + path)
            valid = (isinstance(value.get("version"), str) and bool(value["version"])) if path == "/version" else value.get("status") == "ok"
            if path == "/ready":
                valid = valid and value.get("database") == "ok"
            out[code] = "ok" if valid else "unknown"
        except HTTPError as exc:
            out[code] = "critical" if exc.code >= 500 else "unknown"
        except Exception:
            out[code] = "unknown"
    return out

def github():
    out = {}
    for code, filename in WORKFLOWS.items():
        try:
            runs = read_json(GITHUB + filename + "/runs?branch=main&per_page=10")["workflow_runs"]
            # Ignore manual diagnostics; only scheduled/automatic runs.
            runs = [r for r in runs if r.get("event") in ("schedule", "workflow_run")]
            if not runs:
                continue
            r = runs[0]
            age = age_hours(r.get("created_at"))
            if age is None:
                continue
            if r.get("status") != "completed":
                out[code] = "warning" if age > 1 else "unknown"
            elif r.get("conclusion") == "success":
                out[code] = "warning" if age > 96 else "ok"
            elif r.get("conclusion") in ("failure", "timed_out", "cancelled"):
                out[code] = "critical"
            else:
                out[code] = "unknown"
        except Exception:
            pass
    return out

def financial_state(doc):
    age = age_hours(doc.get("updated_at"))
    if age is None:
        return "unknown"
    if doc.get("state") in ("failed", "timeout"):
        return "critical"
    if age > 8 or doc.get("state") == "partial":
        return "warning"
    if doc.get("state") == "finished":
        return "ok"
    return "unknown"

def receipt_state(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("messages"), list) or not doc["messages"]:
        return "unknown"
    for m in doc["messages"]:
        if not isinstance(m, dict):
            return "unknown"
        if m.get("sent") is not True:
            return "warning"
        receipt = m.get("acceptance")
        if not isinstance(receipt, dict) or receipt.get("delivery_status") != "api_accepted_only":
            return "unknown"
        if receipt.get("http_status") == 200 and receipt.get("request_id"):
            continue
        if receipt.get("http_status") == 409 and receipt.get("accepted_request_id"):
            continue
        return "unknown"
    return "ok"

def database():
    # Explicit operator opt-in to a configured DB; no schema initialization.
    if os.getenv("AGENT_MONITOR_DB_READ") != "1":
        return {}
    from app.db import Session, Document
    from sqlalchemy import text
    out = {}
    with Session() as session:
        if session.bind.dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout = '4000ms'"))
        elif session.bind.dialect.name != "sqlite":
            return {}
        session.execute(text("SELECT 1"))
        out["database"] = "ok"
        def get_doc(key):
            row = session.get(Document, key)
            return json.loads(row.payload) if row else {}
        out["financial_refresh"] = financial_state(get_doc("jobs:data_refresh"))
        # Explicit expected report keys, supplied by trusted operator only.
        keys = os.getenv("AGENT_MONITOR_EXPECTED_OUTBOX_KEYS", "").split(",")
        keys = [k for k in keys if k]
        if keys and len(keys) <= 20 and all(k.startswith(("recommendations:outbox:", "four_rankings:outbox:")) and len(k) <= 240 for k in keys):
            states = [receipt_state(get_doc(k)) for k in keys]
            out["line_receipts"] = "warning" if "warning" in states else "unknown" if "unknown" in states else "ok"
    return out

def main():
    try:
        result = {"api": api, "github": github, "database": database}[sys.argv[1]]()
    except Exception:
        result = {}
    print(json.dumps(result))

if __name__ == "__main__":
    main()
