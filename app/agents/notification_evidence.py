"""Bounded read-only notification evidence, no sender or live quota calls."""
import json, os
from collections import Counter
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from app.agents.audit_aggregate import readonly_session
from app.agents.notification import NotificationAgent
from app.agents.monitor_probe import GITHUB,WORKFLOWS,read_json

def workflow_history(runs, now, days, hour, minute):
    if runs is None:return []
    result=[]
    for offset in range(days):
        day=now.date()-timedelta(days=offset)
        due=now.replace(year=day.year,month=day.month,day=day.day,hour=hour,minute=minute,second=0,microsecond=0)
        if day.weekday()>=5 or due+timedelta(minutes=45)>now:continue
        states=[]
        for run in runs:
            try:
                at=datetime.fromisoformat(run["created_at"].replace("Z","+00:00"))
                if run.get("head_branch")=="main" and run.get("event")=="schedule" and due<=at<due+timedelta(hours=2):
                    states.append(run.get("conclusion") if run.get("status")=="completed" else "running")
            except (ValueError,TypeError,KeyError,AttributeError):continue
        result.append({"date":str(day),"slot":f"{hour:02}:{minute:02}","state":"failed" if any(s in ("failure","timed_out","cancelled") for s in states) else "workflow_success" if "success" in states else "running" if "running" in states else "unknown"})
    return result

def duplicate_keys(docs):
    keys=Counter()
    for doc in docs:
        if not isinstance(doc,dict):continue
        messages=doc.get("messages")
        if not isinstance(messages,list):continue
        for m in messages:
            if isinstance(m,dict) and isinstance(m.get("retry_key"),str) and m["retry_key"]:
                keys[m["retry_key"]]+=1
    return sum(n>1 for n in keys.values())

def signal_summary(docs, now):
    counts=Counter()
    for d in docs:
        if not isinstance(d,dict):counts["unknown"]+=1;continue
        p=d.get("pending")
        if isinstance(p,dict):
            counts["blocked_unknown_reason" if p.get("blocked") else "pending"]+=1
        elif d.get("uncertain_delivery"):counts["uncertain"]+=1
        elif type(d.get("sent_at")) in (int,float) and 0<=now.timestamp()-d["sent_at"]<=14*86400:counts["sent_marker_only"]+=1
        else:counts["no_recent_evidence"]+=1
    return dict(counts)

def read_notifications(*, now, days=7):
    if os.getenv("AGENT_NOTIFICATION_DB_READ")!="1":return {"mode":"shadow","status":"denied"}
    if now.tzinfo is None or type(days) is not int or not 1<=days<=14:return {"mode":"shadow","status":"unknown"}
    now=now.astimezone(ZoneInfo("Asia/Taipei"))
    from app.db import Document
    from app.config import settings
    from sqlalchemy import select
    try:
        with readonly_session() as s:
            def read(key,default=None):
                row=s.get(Document,key)
                return json.loads(row.payload) if row else default
            def prefix(p,limit):
                rows=list(s.scalars(select(Document).where(Document.key.startswith(p,autoescape=True)).limit(limit+1)))
                if len(rows)>limit:raise ValueError("scope limit")
                return {r.key:json.loads(r.payload) for r in rows}
            accounts=prefix("member:",100)
            users=set(settings.users.values())|{k[7:] for k in accounts}
            if len(users)>100:raise ValueError("scope limit")
            active=[u for u in users if accounts.get("member:"+u,{"active":True}).get("active") and not accounts.get("member:"+u,{}).get("password_change_required")]
            result=NotificationAgent().audit(now=now,read=read,users=active,days=days)
            outboxes={}
            for offset in range(days):
                day=now.date()-timedelta(days=offset)
                for p in ("recommendations","four_rankings","watch_digest"):
                    outboxes.update(prefix(f"{p}:outbox:{day}:",200))
            signals=prefix("signal:state:",3000)
            result["duplicate_retry_keys"]=duplicate_keys(outboxes.values())
            result["historical_outboxes"]=len(outboxes)
            result["historical_subscription_verified"]=False
            result["signal_state"]=signal_summary(signals.values(),now)
            result["watch_digest_outboxes"]=sum(k.startswith("watch_digest:") for k in outboxes)
            result["quota_state"]="unknown"
        result["workflow_history"]=[]
        if os.getenv("AGENT_NOTIFICATION_GITHUB_READ")=="1":
            for code,h,m in (("ranking_workflow",11,30),("ranking_workflow",19,30),("scan_workflow",18,17)):
                try:
                    runs=read_json(GITHUB+WORKFLOWS[code]+"/runs?branch=main&per_page=100")["workflow_runs"]
                    result["workflow_history"].extend(workflow_history(runs,now,days,h,m))
                except Exception:pass
        states=[k for row in result["history"] for k in row["counts"]]
        result["severity"]="critical" if result["duplicate_retry_keys"] or "duplicate_risk" in states else "warning" if any(k in states for k in ("possible_missing","partial","pending","receipt_uncertain","expired_or_unknown")) or any(r["state"]=="failed" for r in result["workflow_history"]) else "unknown"
        return result
    except Exception:return {"mode":"shadow","status":"unknown"}
