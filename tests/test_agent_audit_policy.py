from datetime import datetime,timezone
from app.agents.audit_policy import annual_reference,origin,source_state,market_page
from app.agents.supervisor import Supervisor
from app.db import put,get
NOW=datetime(2026,11,26,tzinfo=timezone.utc)

def test_deadline():
    assert annual_reference(NOW.replace(month=3,day=31))==2025
    assert annual_reference(NOW.replace(month=4,day=1))==2026

def test_origins():
    assert origin("https://www.twse.com.tw/a")==origin("https://twse.com.tw/b")
    assert origin("https://twse.com.tw.evil.test")==None

def test_source_states():
    assert source_state({"http_status":429},NOW)=="rate_limited"
    assert source_state({"http_status":401},NOW)=="authorization_error"
    assert source_state({"http_status":503},NOW)=="upstream_error"
    assert source_state({},NOW)=="unknown"

def test_market_page_isolated(monkeypatch):
    from app.db import engine
    assert engine.dialect.name=="sqlite"
    monkeypatch.setenv("AGENT_AUDIT_DB_READ","1")
    snapshot={"verified":True,"method":"OFFICIAL_COMPANY_REGISTRY","at":NOW.timestamp(),"symbols":[f"{i}.TW" for i in range(1000,1021)]}
    put("v26:universe:verified_symbols",snapshot)
    sup=Supervisor(enabled=True)
    first=sup.audit_market(now=NOW,is_admin=True)
    assert len(first["rows"])==20 and first["next_offset"]==20
    assert sup.audit_market(now=NOW,offset=20,is_admin=True)["status"]=="unknown"
    second=sup.audit_market(now=NOW,offset=20,expected_snapshot_at=first["snapshot_at"],is_admin=True)
    assert len(second["rows"])==1 and second["next_offset"] is None
    assert get("v26:universe:verified_symbols")==snapshot
    assert first["verified"] is False

def test_stale_universe():
    assert market_page({"verified":True,"at":0},NOW) is None
