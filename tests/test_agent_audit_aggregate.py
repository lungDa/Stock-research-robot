from datetime import datetime,timezone
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.agents.audit_aggregate import readonly_session,aggregate
from app.agents.supervisor import Supervisor
from app.db import put,get,Document
NOW=datetime(2026,11,26,tzinfo=timezone.utc)

def test_readonly_rejects_write():
    with readonly_session() as session:
        assert session.bind.dialect.name=="sqlite"
        with pytest.raises(DBAPIError):
            session.execute(text("CREATE TABLE audit_forbidden_test (id integer)"))
    put("audit:test",{"ok":True})
    assert get("audit:test")=={"ok":True}

def test_market_snapshot(monkeypatch):
    monkeypatch.setenv("AGENT_AUDIT_DB_READ","1")
    snapshot={"verified":True,"method":"OFFICIAL_COMPANY_REGISTRY","at":NOW.timestamp(),"symbols":[f"{i}.TW" for i in range(1000,1021)]}
    put("v26:universe:verified_symbols",snapshot)
    result=Supervisor(enabled=True).audit_market_snapshot(now=NOW,is_admin=True)
    assert result["status"]=="complete"
    assert result["summary"]["stock_count"]==21
    assert result["verified"] is False
    assert get("v26:universe:verified_symbols")==snapshot

def test_aggregate_rejects_duplicates():
    with pytest.raises(ValueError):
        aggregate(["2330.TW"],[{"symbol":"2330.TW"},{"symbol":"2330.TW"}])

def test_aggregate_denied():
    assert Supervisor().audit_market_snapshot(now=NOW,is_admin=True)["status"]=="denied"


def test_missing_rejected():
    with pytest.raises(ValueError):
        aggregate(["2330.TW"],[])

def test_readonly_dml_and_cleanup():
    put("audit:protected",{"ok":True})
    with readonly_session() as session:
        with pytest.raises(DBAPIError):
            session.execute(text("DELETE FROM "+Document.__tablename__))
    assert get("audit:protected")=={"ok":True}
    put("audit:protected",{"ok":False})
    assert get("audit:protected")=={"ok":False}

def test_same_filing_conflict():
    from app.agents.data_auditor import audit
    def doc(value,url):
        return {"at":NOW.timestamp(),"rows":{"2025":{"eps":value,"field_sources":{"eps":{"url":url,"unit":"TWD","period_end":"2025-12-31","original_filing_id":"filing-2330-2025"}}}}}
    result=audit(["2330.TW"],{"financial:official:2330.TW":doc(10,"https://twse.com.tw/a"),"annual:shared:2330.TW":doc(20,"https://finmindtrade.com/b")},now=NOW)["rows"][0]
    assert result["same_filing_conflicts"]==[("eps","2025")]
    assert result["distinct_origin_conflicts"]==[]

def test_age_promotion():
    from app.agents.audit_policy import rank_repairs
    candidates=[{"symbol":"2330.TW","missing_fields":10,"requested_at":NOW.timestamp()-8*86400},{"symbol":"2317.TW","missing_fields":0,"requested_at":NOW.timestamp()}]
    rows=[{"symbol":"2330.TW","conflicts":[],"invalid":[]},{"symbol":"2317.TW","conflicts":["eps"],"invalid":[]}]
    assert rank_repairs(candidates,rows,NOW)[0]["symbol"]=="2330.TW"
