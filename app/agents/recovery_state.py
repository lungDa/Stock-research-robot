"""In-memory isolated simulation; no external execution or persistence."""
from hashlib import sha256
from threading import RLock
from app.agents.recovery_policy import fresh,circuit,approval,plan_incident,compare
from app.agents.recovery import retry_policy

class RecoverySimulation:
    def __init__(self):
        self._states={}
        self._lock=RLock()
    def plan(self, *, incident, now, evidence):
        if not isinstance(evidence,dict):raise ValueError("evidence")
        reports={}
        for source in ("monitor","data","notification"):
            e=evidence.get(source)
            reports[source]=e.get("report") if isinstance(e,dict) and e.get("source")==source and fresh(e.get("at"),now) else None
        result=plan_incident(incident=incident,observed_at=now,now=now,**reports)
        with self._lock:
            if len(self._states)+len(result["plans"])>1000:raise ValueError("simulation limit")
            for p in result["plans"]:
                s=self._states.setdefault(p["id"],{"attempts":0,"failures":0,"opened_at":None,"approval":"pending","probe":False,"history":[]})
                p["approval_state"]=s["approval"]
                p["retry"]=retry_policy(s["attempts"],s["failures"])
                p["circuit"]=circuit(s["failures"],s["opened_at"],now)
                if p["circuit"]!="closed" or s["attempts"]>=3:
                    p["action"]="hold_and_review" if p["action"]!="do_not_resend" else p["action"]
                p["execution_allowed"]=False
        return result
    def transition(self,key,event,now):
        with self._lock:
            s=self._states.get(key)
            if s is None or len(s["history"])>=32:return False
            if event in ("approve","reject","revoke"):
                next_state=approval(s["approval"],event)
                if next_state=="invalid":return False
                s["approval"]=next_state
            elif event=="simulate_failure":
                if s["approval"]!="approved" or circuit(s["failures"],s["opened_at"],now)!="closed" or s["attempts"]>=3:return False
                s["attempts"]+=1;s["failures"]+=1
                if s["failures"]>=3:s["opened_at"]=now
            elif event=="simulate_probe":
                if s["approval"]!="approved" or circuit(s["failures"],s["opened_at"],now)!="half_open" or s["probe"]:return False
                s["probe"]=True
            else:return False
            s["history"].append(event)
            return True
    def history(self,key):
        with self._lock:
            return tuple(self._states.get(key,{}).get("history",()))

def verify_pair(before,after,now):
    if not isinstance(before,dict) or not isinstance(after,dict):return "unknown"
    if before.get("collector") not in ("monitor","data","notification") or after.get("collector")!=before.get("collector"):return "unknown"
    if not before.get("sample_id") or not after.get("sample_id") or before["sample_id"]==after["sample_id"]:return "unknown"
    return compare(before,after,now)
