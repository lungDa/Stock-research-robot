"""Snapshot-only worker. No live collectors or external actions."""
import json,sys,os
# Disable dotenv before importing any application modules.
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['DATABASE_URL']='sqlite:///:memory:'
if __name__=='__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(18,19))
    resource.setrlimit(resource.RLIMIT_FSIZE,(2000000,2000000))
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
from datetime import datetime,timezone
from dataclasses import asdict
from app.agents.supervisor import Supervisor
from app.agents.contracts import Task,Snapshot,Capability
def analyze(name,p):
    s=Supervisor(enabled=True)
    now=datetime.now(timezone.utc)
    if name=="system_monitor":
        return asdict(s.run(Task("system_monitor",Capability.READ_SNAPSHOT),Snapshot(**p),is_admin=True))
    if name=="data_auditor":
        return s.audit_data(p["symbols"],p["documents"],now=now,is_admin=True)
    if name=="notification":
        return s.audit_notifications(now=now,read=p["documents"].get,users=p["users"],days=p.get("days",7),is_admin=True)
    if name=="recovery":
        return s.plan_recovery(monitor=p.get("monitor"),data=p.get("data"),notification=p.get("notification"),now=now,is_admin=True)
    if name=="research":
        return s.research(**{k:v for k,v in p.items() if k not in ("now","is_admin")},now=now,is_admin=True)
    if name=="risk":
        return s.risk(**{k:v for k,v in p.items() if k not in ("now","is_admin")},now=now,is_admin=True)
    raise ValueError()
if __name__=="__main__":
    try:
        print(json.dumps(analyze(sys.argv[1],json.load(sys.stdin)),allow_nan=False))
    except Exception:
        print('{"mode":"shadow","status":"unknown"}')
