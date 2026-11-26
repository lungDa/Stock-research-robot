import pandas as pd
from app.agents.risk import metrics,market_beta,correlation_value,market_snapshot
from app.services.defensive_model import BENCHMARK_WEIGHTS
from test_agent_research import NOW,DOC
from datetime import timedelta

def test_invalid_tail():
    assert metrics(pd.Series([0.01]*59+[float("nan")])) is None
    assert metrics(pd.Series([-.01]*59+[-1])) is None

def test_beta_and_correlation():
    b=pd.Series([-.01,.02]*30)
    assert abs(market_beta(b*2,b)-2)<1e-9
    assert abs(correlation_value(b,-b)+1)<1e-9
    assert market_beta(b,pd.Series([.01]*60)) is None
    assert correlation_value(b,pd.Series([.01]*60)) is None

def test_market_positive_and_future():
    days=sorted(d for i in range(100) if (d:=NOW.date()-timedelta(days=i)).weekday()<5)
    data={k:[{"date":str(d),"benchmark_id":k,"published_at":str(d)+("T08:00:00+08:00" if k in ("nasdaq_100","sox") else "T14:00:00+08:00"),"source_url":"https://twse.com.tw","previous":100*.94**i,"close":100*.94**(i+1),"return":-.06} for i,d in enumerate(days)] for k in BENCHMARK_WEIGHTS}
    assert market_snapshot(data,NOW,DOC)["level"]==4
    data["sox"][-1]["published_at"]=str(days[-1])+"T10:00:00+08:00"
    assert market_snapshot(data,NOW,DOC)["level"] is None

def test_tail_sample():
    r=metrics(pd.Series([-.1,-.08,-.06]+[.01]*57))
    assert abs(r["cvar95_daily"]-.08)<1e-9
    assert r["var95_daily"]<=r["cvar95_daily"]
