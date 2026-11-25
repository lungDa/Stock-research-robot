from datetime import datetime,timezone
from app.agents.notification import inspect_outbox
from app.agents.supervisor import Supervisor
from app.agents.registry import Registry
NOW=datetime(2026,11,26,12,tzinfo=timezone.utc)
def doc(*messages):
    return {"created_at":NOW.timestamp()-60,"messages":list(messages)}
def entry(key="a",sent=False,receipt=None):
    return {"retry_key":key,"sent":sent,"acceptance":receipt,"text":"private"}
def test_denied():
    assert Supervisor().audit_notifications(now=NOW,read=None,users=[],is_admin=True)["status"]=="denied"
def test_registry():
    assert Registry().resolve("notification") is not None
def test_duplicate():
    assert inspect_outbox(doc(entry(),entry()),NOW,True)[0]=="duplicate_risk"
def test_expired():
    assert inspect_outbox(doc(entry()),NOW,False)[0]=="expired_or_unknown"
def test_pending():
    assert inspect_outbox(doc(entry()),NOW,True)[0]=="pending"
def test_uncertain():
    assert inspect_outbox(doc(entry(sent=True)),NOW,True)[0]=="receipt_uncertain"
def test_accepted():
    assert inspect_outbox(doc(entry(sent=True,receipt={"http_status":200,"request_id":"id"})),NOW,True)[0]=="api_accepted_only"
def test_conflict_receipt():
    assert inspect_outbox(doc(entry(sent=True,receipt={"http_status":409,"accepted_request_id":"id"})),NOW,True)[0]=="api_accepted_only"
