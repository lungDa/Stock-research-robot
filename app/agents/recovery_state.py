"""In-memory isolated simulation; no external execution or persistence."""
from hashlib import sha256
from threading import RLock
from datetime import datetime
from app.agents.notification_policy import recovery_advice
from app.agents.recovery_policy import fresh,circuit,approval,plan_incident,compare
from app.agents.recovery import retry_policy

class RecoverySimulation:
    def __init__(self):
        self._states={}
        self._lock=RLock()
    def plan(self, *, incident, now, evidence, outbox=None):
        if not isinstance(evidence,dict):raise ValueError("evidence")
        reports={}
        for source in ("monitor","data","notification"):
            e=evidence.get(source)
            reports[source]=e.get("report") if isinstance(e,dict) and e.get("source")==source and fresh(e.get("at"),now) else None
        result=plan_incident(incident=incident,observed_at=now,now=now,**reports)
        blockers={p["scope"] for p in result["plans"] if p["source"]=="monitor" and p["severity"]=="critical"}
        if isinstance(outbox,dict) and outbox.get("incident")==incident and fresh(outbox.get("at"),now) and isinstance(outbox.get("key"),str) and 0<len(outbox["key"])<=512:
            advice=recovery_advice(outbox.get("document"),now,same_day=outbox.get("same_day") is True,eligible=outbox.get("eligible"),duplicate=bool(blockers) or any(p["category"]=="notification_duplicate" for p in result["plans"]),error=outbox.get("error","unknown"))
            result["outbox_review"]={"target":sha256(outbox["key"].encode()).hexdigest(),"advice":advice,"execution_allowed":False}
        with self._lock:
            if len(self._states)+sum(p["id"] not in self._states for p in result["plans"])>1000:raise ValueError("simulation limit")
            for p in result["plans"]:
                s=self._states.setdefault(p["id"],{"attempts":0,"failures":0,"opened_at":None,"approval":"pending","probe":False,"history":[],"operations":set(),"approved_at":None,"observed_at":now,"last_at":now})
                s["observed_at"]=max(s["observed_at"],now)
                if s["approval"]=="approved" and not fresh(s["approved_at"],now):s["approval"]="pending"
                p["approval_state"]=s["approval"]
                dependencies={"data":{"database","financial_refresh","refresh_workflow"},"notification":{"database","api_health","api_ready","ranking_workflow","scan_workflow"}}
                if blockers & dependencies.get(p["source"],set()):
                    p["blocked_by_dependency"]=True
                    if p["action"]!="do_not_resend":p["action"]="hold_and_review"
                p["retry"]=retry_policy(s["attempts"],s["failures"])
                p["circuit"]=circuit(s["failures"],s["opened_at"],now)
                if p["circuit"]!="closed" or s["attempts"]>=3:
                    p["action"]="hold_and_review" if p["action"]!="do_not_resend" else p["action"]
                p["execution_allowed"]=False
        return result
    def transition(self,key,event,now,operation_id=None):
        with self._lock:
            s=self._states.get(key)
            if s is None or len(s["history"])>=32 or not isinstance(now,datetime) or now.utcoffset() is None or now<s["last_at"]:return False
            if operation_id is not None and (not isinstance(operation_id,str) or not 1<=len(operation_id)<=128 or operation_id in s["operations"]):return False
            if event.startswith("simulate_") and (not fresh(s["approved_at"],now) or not fresh(s["observed_at"],now)):return False
            if event in ("approve","reject","revoke"):
                next_state=approval(s["approval"],event)
                if next_state=="invalid":return False
                s["approval"]=next_state
                if next_state=="approved":s["approved_at"]=now
            elif event=="simulate_failure":
                if s["approval"]!="approved" or circuit(s["failures"],s["opened_at"],now)!="closed" or s["attempts"]>=3:return False
                s["attempts"]+=1;s["failures"]+=1
                if s["failures"]>=3:s["opened_at"]=now
            elif event=="simulate_probe":
                if s["approval"]!="approved" or circuit(s["failures"],s["opened_at"],now)!="half_open" or s["probe"]:return False
                s["probe"]=True
            elif event in ("simulate_probe_success","simulate_probe_failure"):
                if s["approval"]!="approved" or not s["probe"]:return False
                s["probe"]=False
                if event=="simulate_probe_success":
                    s["failures"]=0;s["attempts"]=0;s["opened_at"]=None
                else:s["opened_at"]=now
            else:return False
            if operation_id is not None:s["operations"].add(operation_id)
            s["last_at"]=now
            s["history"].append(event)
            return True
    def history(self,key):
        with self._lock:
            return tuple(self._states.get(key,{}).get("history",()))

    def export_history(self):
        with self._lock:
            return {"mode":"shadow","events":[{"plan":key,"events":list(s["history"])} for key,s in sorted(self._states.items())],"executed":False}

def verify_pair(before,after,now):
    if not isinstance(before,dict) or not isinstance(after,dict):return "unknown"
    if before.get("collector") not in ("monitor","data","notification") or after.get("collector")!=before.get("collector"):return "unknown"
    if not before.get("sample_id") or not after.get("sample_id") or before["sample_id"]==after["sample_id"]:return "unknown"
    return compare(before,after,now)
