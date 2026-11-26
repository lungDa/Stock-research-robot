"""Pure shadow recovery planner. No execution, persistence or external calls."""
from hashlib import sha256
from datetime import datetime
from app.agents.monitor_v2 import CODES

POLICY={
 "system_failure":("critical","inspect_service_dependencies"),
 "system_warning":("warning","inspect_service_dependencies"),
 "data_conflict":("warning","reconcile_source_evidence"),
 "data_missing":("warning","review_existing_repair_queue"),
 "notification_duplicate":("critical","hold_and_review"),
 "notification_pending":("warning","review_existing_retry_keys"),
 "notification_failure":("warning","inspect_notification_evidence"),
 "notification_accepted":("info","do_not_resend"),
 "unknown":("unknown","collect_evidence"),
}
ORDER={"critical":0,"warning":1,"unknown":2,"info":3}

def count(value):
    return value if type(value) is int and 0<=value<=1000000 else 0

def retry_policy(attempts, failures):
    if type(attempts) is not int or type(failures) is not int or min(attempts,failures)<0:
        return {"state":"unknown","delay_seconds":None}
    if failures>=3 or attempts>=3:return {"state":"open","delay_seconds":None}
    return {"state":"closed","delay_seconds":min(900,30*2**attempts)}

class RecoveryAgent:
    def plan(self, *, monitor, data, notification, now, attempts=None):
        if not isinstance(now,datetime) or now.utcoffset() is None:raise ValueError("timezone required")
        if attempts is None:attempts={}
        if not isinstance(attempts,dict) or len(attempts)>100:raise ValueError("invalid attempts")
        findings=set()
        def add(source,kind,scope):
            findings.add((source,kind,scope))
        for source,report in (("monitor",monitor),("data",data),("notification",notification)):
            if not isinstance(report,dict) or report.get("mode")!="shadow" or report.get("status") in ("denied","unknown","timeout","error"):
                add(source,"unknown","report")
                continue
            if source=="monitor":
                checks=report.get("checks")
                if not isinstance(checks,list) or not checks or len(checks)>len(CODES):add(source,"unknown","report");continue
                for c in checks:
                    if not isinstance(c,dict) or c.get("code") not in (*CODES,"failed_jobs","stale_jobs"):add(source,"unknown","report");continue
                    state=c.get("severity")
                    if state=="critical":add(source,"system_failure",c["code"])
                    elif state=="warning":add(source,"system_warning",c["code"])
                    elif state!="ok":add(source,"unknown",c["code"])
            elif source=="data":
                rows=report.get("rows")
                if not isinstance(rows,list) or not rows or len(rows)>5000:add(source,"unknown","report");continue
                for r in rows:
                    if not isinstance(r,dict):add(source,"unknown","report");continue
                    if r.get("conflicts") or r.get("invalid"):add(source,"data_conflict","financial")
                    expected,complete=r.get("expected_items"),r.get("complete_items")
                    if type(expected) is not int or type(complete) is not int or not 0<=complete<=expected or expected==0:add(source,"unknown","financial")
                    elif complete<expected or count(r.get("stale_sources")):add(source,"data_missing","financial")
                    if count(r.get("unknown_sources")):add(source,"unknown","financial")
            else:
                if count(report.get("duplicate_retry_keys")):add(source,"notification_duplicate","outbox")
                history=report.get("history")
                if not isinstance(history,list) or not history or len(history)>100:add(source,"unknown","report");continue
                for row in history:
                    counts=row.get("counts") if isinstance(row,dict) else None
                    if not isinstance(counts,dict):add(source,"unknown","outbox");continue
                    for state,n in counts.items():
                        if not count(n):continue
                        kind={"duplicate_risk":"notification_duplicate","receipt_uncertain":"notification_duplicate","pending":"notification_pending","partial":"notification_pending","possible_missing":"notification_failure","expired_or_unknown":"notification_failure","api_accepted_only":"notification_accepted"}.get(state,"unknown")
                        add(source,kind,"outbox")
                if report.get("severity") in ("critical","warning"):add(source,"notification_failure","report")
        plans=[]
        for source,kind,scope in sorted(findings):
            severity,action=POLICY[kind]
            key=sha256(f"v1:{source}:{kind}:{scope}".encode()).hexdigest()
            history=attempts.get(key,{})
            if not isinstance(history,dict):history={}
            retry=retry_policy(history.get("attempts",0),history.get("failures",0))
            plans.append({"id":key,"source":source,"category":kind,"scope":scope,"severity":severity,"action":action,"root_cause":"unconfirmed","retry":retry,"approval_required":True,"execution_allowed":False,"verification":"fresh_independent_audit_required"})
        plans.sort(key=lambda p:(ORDER[p["severity"]],p["id"]))
        return {"mode":"shadow","status":"planned","plans":plans,"executed":False}

def verify_simulation(plan, *, before, after):
    # Never certify actual recovery from a simulation.
    if not isinstance(plan,dict) or plan.get("execution_allowed") is not False:return "unknown"
    if before not in ("critical","warning") or after not in ("ok","warning","critical","unknown"):return "unknown"
    return "simulated_improvement" if after=="ok" else "not_verified"
