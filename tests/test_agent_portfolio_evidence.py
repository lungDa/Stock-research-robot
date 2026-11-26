from app.agents.portfolio_evidence import exposures,continuous_sessions,liquidity
from app.agents.risk import metrics,RiskAgent
from test_agent_research import NOW,DOC
from test_agent_risk import position
import pandas as pd

def test_overlap_and_residual():
    p=position()
    e={"research":{"symbol":"0050.TW","quote":{"kind":"ETF"}},"holdings":{"symbol":"0050.TW","basis":"net_asset_weight","as_of":"2026-11-26","observed_at":NOW.isoformat(),"source_url":"https://twse.com.tw","rows":[{"symbol":"2330.TW","kind":"STOCK","weight":.5}]}}
    r=exposures([p,e],{"2330.TW":.2,"0050.TW":.4},{"2330.TW":"technology"},NOW)
    assert abs(r["underlying"]["2330.TW"]-.4)<1e-9
    assert abs(r["unknown_weight"]-.2)<1e-9
    assert len(r["overlaps"]["2330.TW"])==2
    e["holdings"]["rows"]*=2
    assert exposures([p,e],{"2330.TW":.2,"0050.TW":.4},{"2330.TW":"technology"},NOW)["unknown_weight"]==.4

def test_sessions():
    assert continuous_sessions(["2026-11-24","2026-11-25","2026-11-26"],DOC)
    assert not continuous_sessions(["2026-11-24","2026-11-26"],DOC)

def test_tail_quality():
    assert metrics(pd.Series([-.01]*60))["tail_samples"]==3
    assert metrics(pd.Series([-.01]*252))["tail_confidence"]=="larger_sample_not_calibrated"

def test_liquidity_missing():
    assert liquidity(position(),1000,NOW)["status"]=="insufficient_data"

def test_portfolio_report():
    p=position()
    r=RiskAgent().analyze(positions=[p],now=NOW,cash=9000)
    assert r["schema_version"]==2 and r["risk_grade"]=="incomplete"
    assert r["exposure"]["underlying"]["2330.TW"]==.1
    assert r["execution_allowed"] is False
