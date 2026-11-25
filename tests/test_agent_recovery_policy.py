from datetime import datetime,timezone,timedelta
from app.agents.recovery_policy import plan_incident,circuit,approval,compare
from app.agents.supervisor import Supervisor
NOW=datetime(2026,11,26,tzinfo=timezone.utc)
def args():
    return dict(incident="test",observed_at=NOW,now=NOW,monitor={"mode":"shadow","checks":[{"code":"database","severity":"critical"}]},data={"mode":"shadow","rows":[{"expected_items":31,"complete_items":1}]},notification={"mode":"shadow","history":[{"counts":{"partial":1,"api_accepted_only":1}}]})
def test_dependency():
    r=plan_incident(**args())
    assert all(p["blocked_by_dependency"] for p in r["plans"] if p["source"]!="monitor")
    assert any(p["action"]=="do_not_resend" for p in r["plans"])
    assert not r["executed"]
def test_identity():
    a=args();r=plan_incident(**a);assert r==plan_incident(**a)
    a["incident"]="other";assert {p["id"] for p in r["plans"]}.isdisjoint(p["id"] for p in plan_incident(**a)["plans"])
def test_stale():
    a=args();a["observed_at"]=NOW-timedelta(seconds=901)
    assert plan_incident(**a)["status"]=="unknown"
def test_circuit():
    assert circuit(0,None,NOW)=="closed"
    assert circuit(3,NOW,NOW)=="open"
    assert circuit(3,NOW-timedelta(seconds=900),NOW)=="half_open"
def test_approval():
    assert approval("pending","approve")=="approved"
    assert approval("approved","revoke")=="revoked"
    assert approval("rejected","approve")=="invalid"
def test_compare():
    b={"incident":"a","at":NOW-timedelta(seconds=1),"state":"critical"}
    a={"incident":"a","at":NOW,"state":"ok"}
    assert compare(b,a,NOW)=="simulated_improvement"
    assert compare(b,{**a,"incident":"b"},NOW)=="unknown"
def test_denied():
    assert Supervisor().plan_recovery_incident(is_admin=True,**args())["status"]=="denied"
