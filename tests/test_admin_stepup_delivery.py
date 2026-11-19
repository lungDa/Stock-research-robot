"""No real LINE messages; preserve scoped authorization on delivery failures."""
import time
import uuid
from unittest.mock import Mock

import pytest
import requests
from fastapi import HTTPException

from app.db import get, put
from app.day_trader import admin_stepup as stepup


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.setattr(stepup, '_identity', lambda request: ('admin-test', 'device-test',
                        {'expires':time.time()+3600}))
    return stepup._key('device-test')


def test_retry_key_is_canonical_uuid_and_code_not_returned(identity,monkeypatch):
    send=Mock()
    monkeypatch.setattr(stepup.line,'push',send)
    result=stepup.issue(None,'ai_limits')
    key=send.call_args.args[2]
    assert str(uuid.UUID(key))==key
    assert uuid.UUID(key).version==4
    assert result=={'sent':True,'expires_in':300}
    assert get(identity)['grant_expires']==0


def test_failed_delivery_invalidates_challenge_and_allows_explicit_retry(identity,monkeypatch):
    send=Mock(side_effect=[requests.ReadTimeout('private-token user@example.test'),None])
    monkeypatch.setattr(stepup.line,'push',send)
    monkeypatch.setattr(stepup.secrets,'randbelow',lambda n:123456)
    put(identity,{'user':'admin-test','scope':'ai_limits','grant_expires':time.time()+300})
    with pytest.raises(requests.ReadTimeout):stepup.issue(None,'ai_limits')
    state=get(identity)
    assert state['challenge_expires']==state['grant_expires']==0
    assert 'digest' not in state and 'private' not in str(state)
    with pytest.raises(HTTPException):stepup.verify(None,'ai_limits','123456')
    with pytest.raises(HTTPException):stepup.require(None,'ai_limits')
    assert stepup.issue(None,'ai_limits')['sent']
    assert send.call_count==2
    assert send.call_args_list[0].args[2]!=send.call_args_list[1].args[2]
    assert stepup.verify(None,'ai_limits','123456')['authorized']
    assert stepup.require(None,'ai_limits')=='admin-test'
    with pytest.raises(HTTPException):stepup.require(None,'security_settings')


def test_route_logs_only_safe_classification(identity,monkeypatch,caplog):
    from app.api.server import admin_stepup_issue, AdminStepUpRequest
    monkeypatch.setattr(stepup.line,'push',Mock(side_effect=requests.ReadTimeout('secret-token user@example.test')))
    with pytest.raises(HTTPException) as error:
        admin_stepup_issue(AdminStepUpRequest(scope='ai_limits'),None)
    assert error.value.status_code==503
    assert '重新發送' in error.value.detail
    assert 'category=timeout' in caplog.text
    assert 'secret-token' not in caplog.text and 'user@example.test' not in caplog.text
