"""Isolated router: intentionally not mounted on production server."""
import os,json,subprocess,sys,hashlib,threading,tempfile,time
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
    payload=await bounded_json(request,512000)
    try:
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(run_once,user,authorization,name,payload)
    except (ValueError,TypeError):raise HTTPException(400,"Invalid snapshot")
SLOTS=threading.BoundedSemaphore(2)
def invoke(name,payload):
    if not SLOTS.acquire(blocking=False):return {"mode":"shadow","execution_allowed":False,"status":"busy"}
    try:return _invoke(name,payload)
    finally:SLOTS.release()
def _invoke(name,payload,timeout=20):
    try:
        canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False)
        with tempfile.TemporaryDirectory(prefix="agent-shadow-") as tmp:
            with tempfile.TemporaryFile(dir=tmp) as out, tempfile.TemporaryFile(dir=tmp) as err:
                subprocess.run([sys.executable,"-m","app.agents.manager_worker",name],input=canonical.encode(),stdout=out,stderr=err,timeout=timeout,check=True,env=worker_env(tmp))
                out.seek(0)
                raw=out.read(1000001)
                if len(raw)>1000000:raise ValueError()
        result=json.loads(raw)
        if not isinstance(result,dict) or result.get("mode")!="shadow":raise ValueError()
        return {"mode":"shadow","execution_allowed":False,"report":result,"snapshot_digest":hashlib.sha256((name+":"+canonical).encode()).hexdigest(),"observed_at":datetime.now(timezone.utc).isoformat()}
    except subprocess.TimeoutExpired:return {"mode":"shadow","execution_allowed":False,"status":"timeout"}
    except Exception:return {"mode":"shadow","execution_allowed":False,"status":"unknown"}

@router.get("/history")
def history(user=Depends(current_lighthouse_admin),authorization:str=Header(default="")):
    if os.getenv("AGENT_MANAGER_ENABLED")!="1":raise HTTPException(503,"Manager disabled")
    return STORE.history(user,authorization)

@router.post("/review")
async def review(request:Request,user=Depends(current_lighthouse_admin),authorization:str=Header(default="")):
    if not enabled("recovery"):raise HTTPException(503,"Agent disabled")
    payload=await bounded_json(request,4096)
    if not STORE.review(user,authorization,payload):raise HTTPException(409,"Review rejected")
    return STORE.history(user,authorization)

async def bounded_json(request,limit):
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>limit:raise HTTPException(413,"Snapshot too large")
        body.extend(chunk)
    try:
        value=json.loads(body,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value,dict):raise ValueError()
        return value
    except (ValueError,TypeError,RecursionError):raise HTTPException(400,"Invalid snapshot")

def worker_env(tmp):
    return {"PATH":os.defpath,"HOME":tmp,"TMPDIR":tmp,"PYTHON_DOTENV_DISABLED":"1","DATABASE_URL":"sqlite:///:memory:","OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1","PYTHONNOUSERSITE":"1"}

PENDING=set()
LOCK=threading.Lock()
def run_once(user,token,name,payload):
    key=hashlib.sha256(json.dumps([str(user),token,name,payload],sort_keys=True,allow_nan=False).encode()).hexdigest()
    with LOCK:
        if key in PENDING:return {"mode":"shadow","execution_allowed":False,"status":"busy"}
        if len(PENDING)>=2:return {"mode":"shadow","execution_allowed":False,"status":"busy"}
        PENDING.add(key)
    try:
        session=STORE.begin(user,token)
        result=invoke(name,payload)
        return STORE.record(user,token,name,result,payload,expected=session)
    finally:
        with LOCK:PENDING.discard(key)

@router.post("/clear")
def clear(user=Depends(current_lighthouse_admin),authorization:str=Header(default="")):
    STORE.clear(user,authorization)
    return {"mode":"shadow","execution_allowed":False,"status":"cleared"}
