from datetime import timedelta
from app.agents.research_evidence import annual_evidence,downside,historical_valuation,technical_evidence
from test_agent_research import NOW,Q,DOC
from app.services.freshness import TAIPEI

def test_annual_publication_and_audit():
    row={"eps":5,"field_sources":{"eps":{"url":"https://www.twse.com.tw/report","unit":"TWD/share","period_end":"2025-12-31","published_at":"2026-03-01T12:00:00+08:00"}}}
    docs={"financial:official:2330.TW":{"at":NOW.timestamp(),"rows":{"2025":row}}}
    clean,e=annual_evidence("2330.TW",{"2025":row},docs,NOW)
    assert clean["2025"]["eps"]==5 and e[0]["published_at"]
    assert not annual_evidence("2330.TW",{"2025":row},docs,NOW,{"conflicts":[["eps","2025"]]})[0]
    row["field_sources"]["eps"]["published_at"]="2027-01-01T00:00:00+08:00"
    assert not annual_evidence("2330.TW",{"2025":row},docs,NOW)[0]

def test_downside_positive_and_future():
    days=[NOW.astimezone(TAIPEI).date()-timedelta(days=i) for i in range(100)]
    days=sorted(d for d in days if d.weekday()<5)
    pairs=[{"date":str(d),"stock":.01,"benchmark":-.03,"benchmark_published_at":str(d)+"T08:00:00+08:00","stock_observed_at":str(d)+"T14:00:00+08:00","stock_source_url":"https://twse.com.tw","benchmark_source_url":"https://twse.com.tw"} for d in days]
    data={"symbol":"2330.TW","benchmark_id":"tw_electronics","adjustment_status":"verified","alignment":"released_before_taiwan_open","pairs":pairs}
    assert downside(data,"2330.TW",NOW,DOC)["status"]=="available"
    pairs[-1]["benchmark_published_at"]=str(days[-1])+"T10:00:00+08:00"
    assert downside(data,"2330.TW",NOW,DOC)["status"]=="insufficient_data"

def test_historical_pe():
    days=[NOW.date()-timedelta(days=7*i) for i in reversed(range(60))]
    history=[{"date":str(d),"pe":10+i/10,"eps_published_at":str(d)+"T08:00:00+08:00","observed_at":str(d)+"T14:00:00+08:00","source_url":"https://twse.com.tw"} for i,d in enumerate(days)]
    data={"symbol":"2330.TW","history":history}
    assert historical_valuation(data,{**Q,"eps":5},NOW,True)["samples"]==60
    history[0]["eps_published_at"]="2027-01-01T00:00:00+08:00"
    assert "historical_pe" not in historical_valuation(data,Q,NOW,True)

def test_technical_positive():
    days=sorted(d for i in range(100) if (d:=NOW.date()-timedelta(days=i)).weekday()<5)
    bars=[{"date":str(d),"symbol":"2330.TW","completed":True,"adjustment_status":"verified","close":100,"high":101,"low":99,"volume":100,"source_url":"https://twse.com.tw","observed_at":str(d)+"T14:00:00+08:00"} for d in days]
    q={**Q,"adjustment_status":"verified","adjusted_close":100}
    assert technical_evidence(bars,q,NOW.astimezone(TAIPEI),DOC,True)["complete"]
    bars[0]["source_url"]="https://unknown.example"
    assert not technical_evidence(bars,q,NOW.astimezone(TAIPEI),DOC,True)["complete"]
