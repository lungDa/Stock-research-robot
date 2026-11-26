"""Bounded Linux CI fault probes; not a production capacity benchmark."""
import os,sys,time,math,statistics,gc,json
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.api import agent_manager as m
from app.db import put,get
from test_agent_load_stability import GOOD

@pytest.mark.parametrize("script",[
    "import resource; resource.setrlimit(resource.RLIMIT_CPU,(1,1)); exec('while True: pass')",
    "import resource; resource.setrlimit(resource.RLIMIT_AS,(64*1024**2,64*1024**2)); x=bytearray(128*1024**2)",
    "import resource,tempfile; resource.setrlimit(resource.RLIMIT_FSIZE,(4096,4096)); f=tempfile.TemporaryFile(); f.write(b'x'*8192); f.flush()",
    "import resource,os; resource.setrlimit(resource.RLIMIT_NOFILE,(32,32)); files=[os.open('/dev/null',os.O_RDONLY) for _ in range(64)]",
])
def test_resource_fault_contained(monkeypatch,script):
    original=m.subprocess.run
    def fault(args,**kwargs):
        kwargs["timeout"]=8
        return original([sys.executable,"-c",script],**kwargs)
    monkeypatch.setattr(m.subprocess,"run",fault)
    assert m.invoke("system_monitor",GOOD)["status"]=="unknown"
    monkeypatch.setattr(m.subprocess,"run",original)
    assert m.invoke("system_monitor",GOOD)["report"]["status"]=="ok"

@pytest.mark.parametrize("soak",[False,pytest.param(True,marks=pytest.mark.skipif(os.getenv("AGENT_SOAK_CI")!="1",reason="isolated soak CI only"))])
def test_mixed_worker_load_and_parent_health(soak):
    from datetime import datetime,timedelta
    from zoneinfo import ZoneInfo
    from copy import deepcopy
    from test_agent_risk import position
    from app.services.trading_calendar import expected_close
    from fastapi.testclient import TestClient
    from app.api.server import app
    now=datetime.now(ZoneInfo("Asia/Taipei"))
    docs={f"recommendations:calendar:{y}":{"year":y,"closed":[],"opened":[]} for y in (now.year-1,now.year)}
    pos=deepcopy(position())
    pos["research"]["documents"]=docs
    pos["research"]["quote"]["date"]=str(expected_close(now,docs.get))
    inputs=[("system_monitor",GOOD),("data_auditor",{"symbols":["2330.TW"],"documents":docs}),("notification",{"users":["fixture"],"documents":docs}),("recovery",{}),("research",pos["research"]),("risk",{"positions":[pos],"cash":1000})]
    put("agent:test:mixed",{"value":3})
    client=TestClient(app)
    def health():
        start=time.monotonic()
        assert client.get("/health").status_code==200
        assert get("agent:test:mixed")=={"value":3}
        return time.monotonic()-start
    baseline=[health() for _ in range(20)]
    def resources():
        gc.collect()
        with open("/proc/self/status") as f:
            rss=int(next(line.split()[1] for line in f if line.startswith("VmRSS:")))
        with open(f"/proc/self/task/{os.getpid()}/children") as f:
            children=set(f.read().split())
        return rss,children
    rss_before,children_before=resources()
    started=time.monotonic()
    cycles=0
    fd_before=len(os.listdir("/proc/self/fd"))
    timings=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        while cycles<3 or (soak and time.monotonic()-started<600):
            for i in range(0,len(inputs),2):
                futures=[pool.submit(m.invoke,*item) for item in inputs[i:i+2]]
                timings.append(health())
                for f in futures:
                    r=f.result(timeout=30)
                    assert r["execution_allowed"] is False
                    assert r["report"]["mode"]=="shadow"
                    assert r["report"].get("status") not in ("unknown","error","denied")
            cycles+=1
    rss_after,children_after=resources()
    assert children_after<=children_before
    assert rss_after-rss_before<64*1024
    assert len(os.listdir("/proc/self/fd"))<=fd_before+4
    def stats(values):
        return {"mean":statistics.mean(values),"p95":sorted(values)[math.ceil(.95*len(values))-1],"max":max(values),"n":len(values)}
    print("AGENT_SOAK_METRICS",json.dumps({"elapsed":time.monotonic()-started,"cycles":cycles,"workers":cycles*6,"baseline":stats(baseline),"loaded":stats(timings),"rss_delta_kib":rss_after-rss_before,"fd_delta":len(os.listdir("/proc/self/fd"))-fd_before}),flush=True)
    if soak:assert time.monotonic()-started>=600
    assert stats(timings)["p95"]<1
    assert max(timings)<5
    assert not m.PENDING
