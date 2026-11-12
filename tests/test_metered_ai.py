"""Metered real AI invocation: charge only success, reuse daily saved result."""
from app.day_trader import metered_ai

def test_success_and_repeat_do_not_reinvoke(monkeypatch):
    calls=[]
    saved={}
    state=["reserved","cached"]
    monkeypatch.setattr(metered_ai,"reserve",lambda *a:state.pop(0))
    monkeypatch.setattr(metered_ai,"finish",lambda *a,**k:calls.append(("finish",k)) or True)
    monkeypatch.setattr(metered_ai,"put",lambda k,v:saved.__setitem__(k,v))
    monkeypatch.setattr(metered_ai,"get",lambda k:saved.get(k))
    def model(*a,**kw):
        calls.append(("model",kw))
        return {"status":"OK","provider":"gemini","commentary":"測試","scores_unchanged":True}
    monkeypatch.setattr(metered_ai,"review",model)
    first=metered_ai.metered_review("user",{"symbol":"2330.TW"},enabled=True)
    second=metered_ai.metered_review("user",{"symbol":"2330.TW"},enabled=True)
    assert first["charged"] is True
    assert second["reused"] is True and second["charged"] is False
    assert sum(c[0]=="model" for c in calls)==1
    assert len([c for c in calls if c[0]=="finish"])==1

def test_failed_model_releases_quota(monkeypatch):
    calls=[]
    monkeypatch.setattr(metered_ai,"reserve",lambda *a:"reserved")
    monkeypatch.setattr(metered_ai,"finish",lambda *a,**k:calls.append(k) or True)
    monkeypatch.setattr(metered_ai,"review",lambda *a,**k:{"status":"UNAVAILABLE"})
    result=metered_ai.metered_review("user",{"symbol":"2412.TW"},enabled=True)
    assert result["charged"] is False
    assert calls==[{"success":False,"day":metered_ai.today()}]

def test_quota_denial_never_calls_model(monkeypatch):
    monkeypatch.setattr(metered_ai,"reserve",lambda *a:"exhausted")
    monkeypatch.setattr(metered_ai,"review",lambda *a,**k:(_ for _ in ()).throw(AssertionError("model called")))
    result=metered_ai.metered_review("user",{"symbol":"2303.TW"},enabled=True)
    assert result["status"]=="QUOTA_EXHAUSTED"
