"""Ephemeral, session-bound simulation records; no raw snapshot retention."""
from datetime import datetime,timezone
from hashlib import sha256
from threading import RLock
from collections import OrderedDict
from uuid import uuid4
import time,re
from app.agents.supervisor import Supervisor

def safe_report(value):
    # Allowlisted structural keys; omit arbitrary text, URLs, user IDs and receipts.
    keys=set("mode status execution_allowed executed report snapshot_digest observed_at rows history plans findings code severity symbol scope category action id evidence_version approval_state weights cash_weight risk_grade portfolio_metrics samples annualized_volatility max_drawdown var95_daily cvar95_daily confidence factors score coverage complete_items expected_items quality_score counts date slot accepted_messages retry circuit state delay_seconds source root_cause verification verified delivery_verified".split())
    if isinstance(value,dict):
        return {k:safe_report(v) for k,v in value.items() if k in keys or re.fullmatch(r"[0-9]{4,6}\.TW[O]?",k)}
    if isinstance(value,list):return [safe_report(v) for v in value[:500]]
    if isinstance(value,str):
        return value if re.fullmatch(r"(?:[a-f0-9]{64}|[0-9]{4,6}\.TW[O]?|[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9:.+Z-]+)?|[a-z_]{1,64})",value) else "[redacted]"
    return value if value is None or type(value) in (bool,int,float) else None

class ReviewStore:
    def __init__(self):
        self.lock=RLock()
        self.sessions=OrderedDict()
    def _session(self,user,token):
        now=time.monotonic()
        for k in list(self.sessions):
            if now-self.sessions[k]["at"]>900:del self.sessions[k]
        key=sha256((str(user)+"\0"+token).encode()).hexdigest()
        if key not in self.sessions:
            if len(self.sessions)>=32:self.sessions.popitem(last=False)
            self.sessions[key]={"at":now,"runs":[],"sim":None,"review_id":None,"plans":[]}
        return self.sessions[key]
    def record(self,user,token,name,result,payload):
        with self.lock:
            s=self._session(user,token)
            now=datetime.now(timezone.utc)
            clean=safe_report(result)
            if name=="recovery":
                s.update(sim=None,review_id=None,plans=[])
                if result.get("report",{}).get("status")=="planned":
                    sim=Supervisor(enabled=True).recovery_simulation(is_admin=True)
                    incident=uuid4().hex
                    evidence={k:{"source":k,"at":now,"report":payload.get(k)} for k in ("monitor","data","notification")}
                    p=sim.plan(incident=incident,now=now,evidence=evidence)
                    s.update(sim=sim,review_id=incident,plans=safe_report(p["plans"]))
                    clean["review_id"]=incident
                    clean["report"]["plans"]=s["plans"]
            s["runs"]=(s["runs"]+[{"agent":name,"at":now.isoformat(),"status":clean.get("report",{}).get("status",clean.get("status","unknown")),"snapshot_digest":clean.get("snapshot_digest")}])[-100:]
            return clean
    def review(self,user,token,p):
        with self.lock:
            s=self._session(user,token)
            if not s["sim"] or p.get("review_id")!=s["review_id"] or p.get("event") not in ("approve","reject","revoke"):return False
            if not any(x["id"]==p.get("plan") and x["evidence_version"]==p.get("version") for x in s["plans"]):return False
            return s["sim"].transition(p["plan"],p["event"],datetime.now(timezone.utc),operation_id=p.get("operation_id"),expected_version=p["version"])
    def history(self,user,token):
        with self.lock:
            s=self._session(user,token)
            return {"mode":"shadow","execution_allowed":False,"runs":list(s["runs"]),"review":s["sim"].export_history() if s["sim"] else None}
