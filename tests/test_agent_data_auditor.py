from datetime import datetime, timezone
from app.agents.supervisor import Supervisor
from app.agents.data_auditor import audit
import pytest

NOW=datetime(2026,11,26,tzinfo=timezone.utc)
def test_denied():
    assert Supervisor().audit_data(["2330.TW"],{},now=NOW)["status"]=="denied"

def test_empty():
    r=Supervisor(enabled=True).audit_data(["2330.TW"],{},now=NOW,is_admin=True)
    assert r["rows"][0]["complete_items"]==0
    assert r["rows"][0]["quality_score"]==0
    assert r["verified"] is False
    assert r["repair_priority"][0]["symbol"]=="2330.TW"

def test_invalid_symbol():
    with pytest.raises(ValueError):
        audit(["secret"],{},now=NOW)

def test_conflict_and_invalid():
    def doc(v):
        return {"at":NOW.timestamp(),"rows":{"2025":{"eps":v,"cash_yield_pct":-1,"source_url":"secret","unit":"TWD","period_end":"2025-12-31"}}}
    r=audit(["2330.TW"],{"financial:official:2330.TW":doc(10),"annual:shared:2330.TW":doc(20)},now=NOW)
    assert ("eps","2025") in r["rows"][0]["conflicts"]
    assert ("cash_yield_pct","2025") in r["rows"][0]["invalid"]
    assert "secret" not in str(r)
