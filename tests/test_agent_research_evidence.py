from app.agents.research_evidence import annual_evidence,technical_evidence,downside,valuation
from test_agent_research import NOW,Q,DOC

def test_unproven_annual_removed():
    rows,e=annual_evidence("2330.TW",{"2025":{"eps":10}}, {},NOW)
    assert rows=={} and e==[]

def test_missing_technical_metadata():
    assert not technical_evidence([{}]*60,Q,NOW,DOC,True)["complete"]

def test_defensive_missing():
    assert downside({},"2330.TW",NOW,DOC)["status"]=="insufficient_data"

def test_valuation_scenario():
    q={**Q,"eps":5}
    r=valuation({"symbol":"2330.TW","eps":5,"multiples":[10,15,20]},q,NOW,True)
    assert r["scenario"]==[50,75,100]
    assert "scenario" not in valuation({"symbol":"2330.TW","eps":6,"multiples":[10,15,20]},q,NOW,True)
