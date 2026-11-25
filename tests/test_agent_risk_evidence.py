from app.agents.risk_evidence import beta,valid_returns,sector_evidence
from app.agents.risk import metrics
from app.services.defensive_model import BENCHMARK_WEIGHTS
from test_agent_research import NOW,DOC
from test_agent_risk import position
from app.services.freshness import TAIPEI
import pandas as pd

def test_sector():
    p=position()
    assert sector_evidence(p,"2330.TW",NOW)=="unknown"
    p["sector_evidence"]={"symbol":"2330.TW","sector":"technology","source_url":"https://twse.com.tw","observed_at":NOW.isoformat()}
    assert sector_evidence(p,"2330.TW",NOW)=="technology"

def test_invalid_returns():
    assert metrics(pd.Series([float("nan")]*60)) is None
    assert metrics(pd.Series([-1.]*60)) is None

def test_beta_positive():
    days=pd.bdate_range(end="2026-11-26",periods=60).strftime("%Y-%m-%d")
    rows=[]
    price=100.
    for i,d in enumerate(days):
        r=.01 if i%2 else -.01
        close=price*(1+r)
        rows.append({"date":d,"previous":price,"close":close,"return":r,"observed_at":d+"T14:00:00+08:00","source_url":"https://twse.com.tw"})
        price=close
    s=pd.Series([2*r["return"] for r in rows],index=days)
    b={"id":"TAIEX","basis":"total_return","rows":rows}
    assert abs(beta(s,b,NOW)-2)<1e-9
    rows[-1]["observed_at"]="2027-01-01T14:00:00+08:00"
    assert beta(s,b,NOW) is None
