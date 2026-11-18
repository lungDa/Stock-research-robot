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


@pytest.mark.parametrize('status,category',[(401,'AUTH_FAILED'),(403,'AUTH_FAILED'),
                                          (429,'RATE_LIMITED'),(500,'UPSTREAM_ERROR')])
def test_diagnostics_never_expose_provider_response(status,category):
    import requests,json
    def fail(*args):
        response=requests.Response();response.status_code=status
        response._content=b'private-provider-body'
        raise requests.HTTPError('secret-token private-user',response=response)
    result=review(REPORT,enabled=True,caller=fail)
    assert result['failure_category']==category
    assert 'secret-token' not in json.dumps(result)
    assert 'private' not in json.dumps(result)


def test_readiness_does_not_call_providers_or_reveal_keys(monkeypatch):
    from app.day_trader.dual_ai import readiness
    monkeypatch.setenv('GEMINI_API_KEY','private-key')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    status=readiness()
    assert status['providers']==['gemini']
    assert status['verified'] is False
    assert 'private-key' not in str(status)


def test_timeout_then_unconfigured_retains_actionable_cause():
    import requests
    def call(provider,payload):
        if provider=='gemini':raise requests.Timeout('private connection')
    result=review(REPORT,enabled=True,caller=call)
    assert result['failure_category']=='TIMEOUT'
