from app.agents.risk import RiskAgent,metrics
from app.agents.supervisor import Supervisor
from test_agent_research import NOW,Q,DOC
import pandas as pd

def position():
    return {"quantity":10,"currency":"TWD","sector":"technology","research":{"symbol":"2330.TW","quote":Q,"documents":DOC}}

def test_risk_denied():
    assert Supervisor().risk(is_admin=True)["status"]=="denied"
    assert Supervisor(enabled=True).risk(is_admin=1)["status"]=="denied"

def test_concentration_and_stress():
    r=RiskAgent().analyze(positions=[position()],now=NOW,cash=1000)
    assert r["weights"]["2330.TW"]==.5
    assert r["stress_returns"]["-0.2"]==-.1
    assert r["risk_grade"]=="limit_breach"
    assert r["portfolio_metrics"] is None
    assert r["execution_allowed"] is False

def test_duplicate_rejected():
    assert Supervisor(enabled=True).risk(is_admin=True,positions=[position(),position()],now=NOW)["status"]=="unknown"

def test_metrics():
    r=metrics(pd.Series([-.01]*60))
    assert r["max_drawdown"]>.4
    assert abs(r["var95_daily"]-.01)<1e-9
    assert abs(r["cvar95_daily"]-.01)<1e-9
