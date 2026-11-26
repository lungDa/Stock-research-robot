from copy import deepcopy
from datetime import timedelta
import json
import pytest
from app.agents.risk import RiskAgent,market_snapshot
from app.agents.portfolio_evidence import exposures,liquidity
from app.services.defensive_model import BENCHMARK_WEIGHTS
from test_agent_research import NOW,DOC,Q
from test_agent_risk import position

def sample(symbol):
    p=deepcopy(position())
    x=p["research"]
    x["symbol"]=symbol
    x["quote"]={**Q,"symbol":symbol,"adjustment_status":"verified","adjusted_close":100}
    days=sorted(d for i in range(100) if (d:=NOW.date()-timedelta(days=i)).weekday()<5)
    x["bars"]=[]
    for i,d in enumerate(days):
        price=100 if i%2==len(days)%2 else 99
        if i==len(days)-1:price=100
        x["bars"].append({"symbol":symbol,"date":str(d),"close":price,"high":price+1,"low":price-1,"volume":10000,"raw_close":price,"raw_high":price+1,"raw_low":price-1,"raw_volume":10000,"volume_unit":"shares","adjustment_factor":1,"adjustment_status":"verified","completed":True,"observed_at":str(d)+"T14:00:00+08:00","source_url":"https://twse.com.tw","adjustment_source_url":"https://twse.com.tw"})
    p["sector_evidence"]={"symbol":symbol,"sector":"technology","observed_at":NOW.isoformat(),"source_url":"https://twse.com.tw"}
    return p

def test_positive_portfolio():
    a,b=sample("2330.TW"),sample("2317.TW")
    r=RiskAgent().analyze(positions=[a,b],cash=8000,now=NOW)
    assert r["portfolio_metrics"]["samples"]>=60
    assert r["correlation"]["2330.TW"]["2317.TW"]==pytest.approx(1)
    assert sum(r["weights"].values())+r["cash_weight"]==pytest.approx(1)
    assert r["stress_returns"]["-0.2"]==pytest.approx(-.04)
    assert r["positions"]["2330.TW"]["liquidity"]["status"]=="available"
    assert r["execution_allowed"] is False
    json.dumps(r,allow_nan=False)
    assert r["evidence_version"]==RiskAgent().analyze(positions=[a,b],cash=8000,now=NOW)["evidence_version"]

def test_liquidity_value():
    p=sample("2330.TW")
    r=liquidity(p,1000,NOW)
    assert r["average_daily_value_twd"]==pytest.approx(sum(b["raw_close"]*10000 for b in p["research"]["bars"][-20:])/20)
    p["research"]["bars"][-1]["volume_unit"]="lots"
    assert liquidity(p,1000,NOW)["status"]=="insufficient_data"

def test_constituent_and_conservation():
    p={"research":{"symbol":"0050.TW","quote":{"kind":"ETF"}},"holdings":{"symbol":"0050.TW","basis":"net_asset_weight","as_of":"2026-11-26","observed_at":NOW.isoformat(),"source_url":"https://twse.com.tw","rows":[{"symbol":"2330.TW","kind":"STOCK","weight":.8,"sector_evidence":{"symbol":"2330.TW","sector":"technology","observed_at":NOW.isoformat(),"source_url":"https://twse.com.tw"}}]}}
    r=exposures([p],{"0050.TW":.5},{},NOW)
    assert r["sectors"]["technology"]==pytest.approx(.4)
    assert sum(r["sectors"].values())==pytest.approx(.5)
    assert sum(r["underlying"].values())+r["unknown_weight"]==pytest.approx(.5)
    p["holdings"]["rows"][0]["weight"]=1.01
    assert exposures([p],{"0050.TW":.5},{},NOW)["unknown_weight"]==.5
