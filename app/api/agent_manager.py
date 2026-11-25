"""Isolated router: intentionally not mounted on production server."""
import os,json,subprocess,sys,hashlib,threading
from datetime import datetime,timezone
from app.agents.manager_review import ReviewStore, safe_report
from fastapi import Header
STORE=ReviewStore()
from fastapi import APIRouter,Depends,HTTPException,Request
from app.api.security import current_lighthouse_admin
from app.agents.registry import Registry
router=APIRouter(prefix="/admin/agents")
NAMES=("system_monitor","data_auditor","notification","recovery","research","risk")
def enabled(name):
    return os.getenv("AGENT_MANAGER_ENABLED")=="1" and os.getenv("AGENT_MANAGER_"+name.upper())=="1"
@router.get("/overview")
def overview(user=Depends(current_lighthouse_admin)):
    return {"mode":"shadow","execution_allowed":False,"agents":[{"name":n,"enabled":enabled(n),"registered":Registry().resolve(n) is not None} for n in NAMES]}
@router.post("/run/{name}")
async def run(name:str,request:Request,user=Depends(current_lighthouse_admin),authorization:str=Header(default="")):
    if name not in NAMES:raise HTTPException(404,"Unknown agent")
    if not enabled(name):raise HTTPException(503,"Agent disabled")
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>512000:raise HTTPException(413,"Snapshot too large")
    try:
        payload=json.loads(body)
        if not isinstance(payload,dict):raise ValueError()
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(invoke,name,payload)
        return STORE.record(user,authorization,name,result,payload)
    except (ValueError,TypeError):raise HTTPException(400,"Invalid snapshot")
SLOTS=threading.BoundedSemaphore(2)
def invoke(name,payload):
    if not SLOTS.acquire(blocking=False):return {"mode":"shadow","execution_allowed":False,"status":"busy"}
    try:return _invoke(name,payload)
    finally:SLOTS.release()
def _invoke(name,payload,timeout=20):
    try:
        canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False)
        p=subprocess.run([sys.executable,"-m","app.agents.manager_worker",name],input=json.dumps(payload,allow_nan=False),text=True,capture_output=True,timeout=timeout,check=True)
        if len(p.stdout)>1000000:raise ValueError()
        result=json.loads(p.stdout)
        if not isinstance(result,dict) or result.get("mode")!="shadow":raise ValueError()
        return {"mode":"shadow","execution_allowed":False,"report":result,"snapshot_digest":hashlib.sha256((name+":"+canonical).encode()).hexdigest(),"observed_at":datetime.now(timezone.utc).isoformat()}
    except subprocess.TimeoutExpired:return {"mode":"shadow","execution_allowed":False,"status":"timeout"}
    except Exception:return {"mode":"shadow","execution_allowed":False,"status":"unknown"}

@router.get("/history")
def history(user=Depends(current_lighthouse_admin),authorization:str=Header(default="")):
    if os.getenv("AGENT_MANAGER_ENABLED")!="1":raise HTTPException(503,"Manager disabled")
    return STORE.history(user,authorization)

@router.post("/review")
def review(payload:dict,user=Depends(current_lighthouse_admin),authorization:str=Header(default="")):
    if not enabled("recovery"):raise HTTPException(503,"Agent disabled")
    if not STORE.review(user,authorization,payload):raise HTTPException(409,"Review rejected")
    return STORE.history(user,authorization)
