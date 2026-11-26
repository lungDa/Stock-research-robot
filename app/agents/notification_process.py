"""Hard subprocess deadline for opt-in notification collection."""
import json,os,subprocess,sys
from datetime import datetime

def _run_child(command,timeout):
    return subprocess.run(command,capture_output=True,timeout=timeout,check=True)

def collect(*,now,days=7,timeout=35):
    if os.getenv("AGENT_NOTIFICATION_DB_READ")!="1":return {"mode":"shadow","status":"denied"}
    if now.tzinfo is None or type(days) is not int or not 1<=days<=14 or type(timeout) not in (int,float) or not 0<timeout<=60:return {"mode":"shadow","status":"unknown"}
    try:
        p=_run_child([sys.executable,"-m","app.agents.notification_process",now.isoformat(),str(days)],timeout)
        if len(p.stdout)>2_000_000:return {"mode":"shadow","status":"unknown"}
        r=json.loads(p.stdout)
        if not isinstance(r,dict) or r.get("mode")!="shadow" or r.get("status") not in ("complete","unknown","denied"):raise ValueError()
        return r
    except subprocess.TimeoutExpired:return {"mode":"shadow","status":"timeout"}
    except Exception:return {"mode":"shadow","status":"unknown"}

if __name__=="__main__":
    from app.agents.notification_evidence import read_notifications
    try:
        result=read_notifications(now=datetime.fromisoformat(sys.argv[1]),days=int(sys.argv[2]))
    except Exception:result={"mode":"shadow","status":"unknown"}
    print(json.dumps(result))
