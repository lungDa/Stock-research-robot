"""Pure incident policy; no execution or durable state."""
from datetime import datetime
from hashlib import sha256
from app.agents.notification_policy import recovery_advice
from app.agents.recovery import RecoveryAgent

def fresh(at,now):
    return isinstance(at,datetime) and at.utcoffset() is not None and 0<=(now-at).total_seconds()<=900

def circuit(failures,opened_at,now):
    if type(failures) is not int or failures<0:return "unknown"
    if failures<3:return "closed"
    if not isinstance(opened_at,datetime) or opened_at.utcoffset() is None:return "open"
    return "half_open" if (now-opened_at).total_seconds()>=900 else "open"

def approval(state,event):
    return {("pending","approve"):"approved",("pending","reject"):"rejected",("approved","revoke"):"revoked"}.get((state,event),"invalid")

def compare(before,after,now):
    if not isinstance(before,dict) or not isinstance(after,dict):return "unknown"
    if not fresh(before.get("at"),now) or not fresh(after.get("at"),now):return "unknown"
    if not before.get("incident") or before.get("incident")!=after.get("incident") or after["at"]<=before["at"]:return "unknown"
    if before.get("state") in ("critical","warning") and after.get("state")=="ok":return "simulated_improvement"
    return "not_verified"

def plan_incident(*,incident,observed_at,now,monitor,data,notification,outbox=None,eligible=None,same_day=False,error="unknown",attempts=None):
    if not isinstance(incident,str) or not 1<=len(incident)<=128 or not fresh(observed_at,now):
        return {"mode":"shadow","status":"unknown","plans":[],"executed":False}
    result=RecoveryAgent().plan(monitor=monitor,data=data,notification=notification,now=now,attempts=attempts)
    plans=result["plans"]
    dependency=any(p["source"]=="monitor" and p["scope"]=="database" and p["severity"]=="critical" for p in plans)
    duplicate=any(p["category"]=="notification_duplicate" for p in plans)
    advice=recovery_advice(outbox,now,same_day=same_day,eligible=eligible,duplicate=duplicate,error=error) if outbox is not None else "manual_review"
    for p in plans:
        p["id"]=sha256((incident+":"+p["id"]).encode()).hexdigest()
        p["approval_state"]="pending"
        p["root_cause"]="database_dependency_hypothesis" if dependency and p["source"]!="monitor" else "unconfirmed"
        p["blocked_by_dependency"]=dependency and p["source"]!="monitor"
        if p["source"]=="notification":
            p["action"]="do_not_resend" if p["category"]=="notification_accepted" else "hold_and_review" if duplicate or dependency else advice
        elif p["blocked_by_dependency"]:p["action"]="collect_evidence"
    return result
