"""Sanitized notification evidence. Never sends or changes retry keys."""
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from app.agents.notification import inspect_outbox

def trigger(run):
    event=run.get("event")
    if event=="workflow_dispatch":return "manual_preview_or_send"
    if event=="workflow_run":return "upstream_wakeup"
    if event!="schedule":return "unknown"
    # GitHub creation time is not the original cron expression.
    return "scheduled_primary_or_compensation"

def job_evidence(run,jobs):
    counts=Counter()
    for job in jobs:
        for step in job.get("steps",[]):
            name=step.get("name")
            code={"Send opted-in digest":"signal","Send daily watchlist report":"watch_digest","Build personal market recommendations":"ranking"}.get(name)
            if code:
                state=step.get("conclusion")
                counts[code+":"+ (state if state in ("success","failure","skipped","cancelled","timed_out") else "unknown")]+=1
    return {"trigger":trigger(run),"steps":dict(counts),"delivery_verified":False}

def digest_evidence(outboxes,now):
    counts=Counter()
    for key,doc in outboxes.items():
        if not key.startswith("watch_digest:outbox:"):continue
        day=key.split(":")[2]
        state,_,_=inspect_outbox(doc,now,day==str(now.date()))
        counts[state]+=1
    return dict(counts)

def quota_evidence(docs):
    # Only explicit structured evidence; blocked or missing does not imply 429.
    counts=Counter()
    for doc in docs:
        if not isinstance(doc,dict):continue
        entries=doc.get("messages",[])
        if not isinstance(entries,list):entries=[]
        for m in entries:
            if not isinstance(m,dict):continue
            r=m.get("acceptance")
            if isinstance(r,dict) and r.get("http_status")==429:counts["http_429"]+=1
        if doc.get("status")=="quota_exhausted":counts["quota_exhausted"]+=1
    return dict(counts) or {"unknown":1}

def pending_keys(signals):
    return [{"messages":[d["pending"]]} for d in signals if isinstance(d,dict) and isinstance(d.get("pending"),dict)]
