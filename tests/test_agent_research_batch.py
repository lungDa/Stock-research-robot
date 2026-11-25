from test_agent_research import NOW,Q,DOC
from app.agents.research import ResearchAgent
from app.agents.supervisor import Supervisor

def test_version_and_batch():
    a=ResearchAgent()
    x={"symbol":"2330.TW","quote":Q,"documents":DOC}
    r=a.analyze(now=NOW,**x)
    assert r["evidence_version"]==a.analyze(now=NOW,**x)["evidence_version"]
    assert r["evidence_version"]!=a.analyze(now=NOW,**{**x,"quote":{**Q,"price":101}})["evidence_version"]
    b=a.batch(now=NOW,snapshots=[x])
    assert b["reports"][0]["evidence_version"]==r["evidence_version"]
    assert b["comparison"]["STOCK"]==[]
    assert Supervisor().research_batch(is_admin=True)["status"]=="denied"

def test_etf():
    q={**Q,"symbol":"0050.TW","kind":"ETF","yield":4,"yield_basis":"trailing_paid_365d","expense_ratio":.002,"expense_ratio_basis":"annual_total_expense"}
    for k in ("yield","expense_ratio"):
        q[k+"_evidence"]={"source_url":"https://twse.com.tw","observed_at":NOW.isoformat()}
    r=ResearchAgent().analyze(symbol=q["symbol"],quote=q,documents=DOC,now=NOW)
    assert r["financial_audit"] is None and r["kind"]=="ETF"
    assert r["valuation"]["scope"]=="not_applicable_etf"
    assert r["confidence"]>0
