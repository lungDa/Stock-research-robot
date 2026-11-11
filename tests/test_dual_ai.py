import pytest
from app.day_trader.dual_ai import review

REPORT={"symbol":"2330.TW","technical":{"score":70},"fundamental_score":80}

def test_disabled_never_calls_provider():
    def fail(*args):raise AssertionError("must not call")
    assert review(REPORT,caller=fail)["status"]=="DISABLED"

def test_fallback_and_scores_immutable():
    seen=[]
    def fake(provider,payload):
        seen.append(provider)
        if provider=="gemini":raise ValueError("provider unavailable")
        assert "2330.TW" in payload
        return "量價趨勢偏強，但仍需風險控管"
    before=REPORT.copy()
    result=review(REPORT,enabled=True,caller=fake)
    assert seen==["gemini","openai"]
    assert result["provider"]=="openai"
    assert result["execution_enabled"] is False
    assert REPORT==before

def test_no_secret_fields_transmitted():
    def fake(provider,payload):
        assert "secret_token" not in payload
        return "研究解讀"
    result=review({**REPORT,"secret_token":"never-send"},enabled=True,caller=fake)
    assert result["status"]=="OK"

def test_invalid_provider_rejected():
    with pytest.raises(ValueError):review(REPORT,primary="unknown")
