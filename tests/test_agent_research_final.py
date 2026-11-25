from test_agent_research import NOW,Q,DOC
from app.agents.research import ResearchAgent
from app.services.multifactor import DEFAULT
from app.agents.supervisor import Supervisor

def test_batch_isolates_invalid():
    x={"symbol":"2330.TW","quote":Q,"documents":DOC}
    r=ResearchAgent().batch(now=NOW,snapshots=[x,{"symbol":"2317.TW","quote":Q,"documents":DOC}])
    assert len(r["reports"])==1 and r["errors"]==[{"index":1,"status":"invalid_snapshot"}]

def test_effective_config_digest():
    a=ResearchAgent()
    x={"symbol":"2330.TW","quote":Q,"documents":DOC,"now":NOW}
    assert a.analyze(**x)["evidence_version"]==a.analyze(**x,config=DEFAULT)["evidence_version"]

def test_etf_missing_classification():
    r=Supervisor(enabled=True).research(is_admin=True,symbol="0050.TW",quote={**Q,"symbol":"0050.TW","kind":"ETF"},documents=DOC,now=NOW)
    assert r["status"]=="unknown"

def test_etf_volatility():
    from datetime import timedelta
    days=sorted(d for i in range(100) if (d:=NOW.date()-timedelta(days=i)).weekday()<5)
    bars=[]
    for i,d in enumerate(days):
        c=100+i%2
        bars.append({"date":str(d),"symbol":"0050.TW","completed":True,"adjustment_status":"verified","close":c,"high":c+1,"low":c-1,"raw_close":c,"raw_high":c+1,"raw_low":c-1,"adjustment_factor":1,"adjustment_source_url":"https://twse.com.tw","volume":100,"source_url":"https://twse.com.tw","observed_at":str(d)+"T14:00:00+08:00"})
    q={**Q,"symbol":"0050.TW","kind":"ETF","adjustment_status":"verified","adjusted_close":bars[-1]["close"],"classification":{"symbol":"0050.TW","kind":"ETF","source_url":"https://twse.com.tw","observed_at":NOW.isoformat()}}
    r=ResearchAgent().analyze(symbol=q["symbol"],quote=q,documents=DOC,now=NOW,bars=bars)
    assert r["technical"]["complete"]
    assert next(c for c in r["factors"]["checks"] if c["metric"]=="volatility")["value"]>0
