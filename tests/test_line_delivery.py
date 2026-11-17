import asyncio
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
import requests
from starlette.requests import Request

from app.channels import webhook, commands
from app.db import get, put
from tests.test_api import signed


def event(id='delivery-1'):
    return {'type':'message','webhookEventId':id,'replyToken':'private-reply-token',
            'source':{'type':'user','userId':'Uprivate'},'message':{'type':'text','text':'通知開啟'}}


def test_failed_reply_replays_saved_response_without_repeating_command(monkeypatch):
    command=Mock(return_value={'type':'text','text':'已更新'})
    reply=Mock(side_effect=[requests.ReadTimeout('private-token'),None])
    monkeypatch.setattr(commands,'respond',command)
    monkeypatch.setattr(webhook.line,'reply',reply)
    assert not webhook.deliver([event()])
    assert webhook.deliver([event()])
    assert webhook.deliver([event()])
    command.assert_called_once()
    assert reply.call_count==2 and reply.call_args_list[0]==reply.call_args_list[1]
    assert get('event:delivery-1')['status']=='done'


@pytest.mark.parametrize('error,expected',[(RuntimeError('secret user@example.test'),webhook.COMMAND_FAILED),
                                        (requests.ReadTimeout('private-token'),webhook.TIMEOUT)])
def test_command_failure_replies_safely_and_does_not_repeat(monkeypatch,caplog,error,expected):
    command=Mock(side_effect=error);reply=Mock()
    monkeypatch.setattr(commands,'respond',command);monkeypatch.setattr(webhook.line,'reply',reply)
    assert webhook.deliver([event()]) and webhook.deliver([event()])
    command.assert_called_once();reply.assert_called_once_with('private-reply-token',expected)
    assert all(value not in caplog.text for value in ('private-token','user@example.test','Uprivate'))


def test_database_failure_still_attempts_clear_notice_without_command(monkeypatch):
    @contextmanager
    def broken(*args):
        raise RuntimeError('database secret')
        yield
    monkeypatch.setattr(webhook,'leased',broken)
    command=Mock();reply=Mock()
    monkeypatch.setattr(commands,'respond',command);monkeypatch.setattr(webhook.line,'reply',reply)
    assert not webhook.deliver([event()])
    command.assert_not_called();reply.assert_called_once_with('private-reply-token',webhook.UNAVAILABLE)


def test_interrupted_command_is_not_run_again(monkeypatch):
    put('event:delivery-1',{'status':'processing','at':0})
    command=Mock();reply=Mock()
    monkeypatch.setattr(commands,'respond',command);monkeypatch.setattr(webhook.line,'reply',reply)
    assert webhook.deliver([event()])
    command.assert_not_called();reply.assert_called_once_with('private-reply-token',webhook.COMMAND_FAILED)


def test_one_failure_does_not_hide_next_event(monkeypatch):
    monkeypatch.setattr(commands,'respond',Mock(return_value='ok'))
    reply=Mock(side_effect=[requests.ConnectionError(),None]);monkeypatch.setattr(webhook.line,'reply',reply)
    assert not webhook.deliver([event('one'),event('two')])
    assert get('event:two')['status']=='done'


def request(body,headers):
    async def receive():return {'type':'http.request','body':body,'more_body':False}
    return Request({'type':'http','method':'POST','path':'/line/webhook',
                    'headers':[(k.encode(),v.encode()) for k,v in headers.items()]},receive)


@pytest.mark.parametrize('maintenance',[True,False])
def test_maintenance_or_unavailable_notice_verifies_signature_and_never_writes(monkeypatch,maintenance):
    from app.api.server import unavailable_webhook
    # Keep this unit test independent of the platform's threadpool. HTTP route
    # integration is also exercised by the existing TestClient suite in CI.
    async def inline(func,*args):return func(*args)
    monkeypatch.setattr(asyncio,'to_thread',inline)
    command=Mock();reply=Mock()
    monkeypatch.setattr(commands,'respond',command);monkeypatch.setattr(webhook.line,'reply',reply)
    monkeypatch.setattr(webhook,'put',Mock(side_effect=AssertionError('must not write')))
    monkeypatch.setattr(webhook,'get',Mock(side_effect=AssertionError('must not read')))
    monkeypatch.setattr(webhook,'leased',Mock(side_effect=AssertionError('must not lease')))
    body,headers=signed({'events':[event()]})
    response=asyncio.run(unavailable_webhook(request(body,headers),maintenance))
    assert response.status_code==200
    reply.assert_called_once_with('private-reply-token',webhook.MAINTENANCE if maintenance else webhook.UNAVAILABLE)
    command.assert_not_called();reply.reset_mock()
    response=asyncio.run(unavailable_webhook(request(body,{}),maintenance))
    assert response.status_code==503;reply.assert_not_called()


def test_simple_help_does_not_depend_on_member_database(monkeypatch):
    monkeypatch.setattr(commands,'can_use_personal',Mock(side_effect=RuntimeError('offline')))
    assert '2330' in commands.respond('Uprivate','查詢')['text']
    assert commands.respond('Uprivate','功能選單')['type']=='flex'
    assert '功能選單' in commands.respond('Uprivate','使用說明')['text']


def test_malformed_events_are_ignored_without_breaking_batch(monkeypatch):
    reply=Mock();monkeypatch.setattr(webhook.line,'reply',reply)
    assert webhook.deliver([None,{},{'source':None},{'source':{'type':'user'},'message':None}])
    reply.assert_not_called()


def test_busy_event_never_executes_or_replies_twice(monkeypatch):
    @contextmanager
    def busy(*args):yield False
    monkeypatch.setattr(webhook,'leased',busy)
    command=Mock();reply=Mock()
    monkeypatch.setattr(commands,'respond',command);monkeypatch.setattr(webhook.line,'reply',reply)
    assert not webhook.deliver([event()])
    command.assert_not_called();reply.assert_not_called()


def test_pending_storage_failure_reports_uncertainty_and_does_not_reexecute(monkeypatch):
    original_put=webhook.put
    def fail_pending(key,value):
        if value.get('status')=='pending':raise RuntimeError('private database url')
        return original_put(key,value)
    monkeypatch.setattr(webhook,'put',fail_pending)
    command=Mock(return_value='changed');reply=Mock()
    monkeypatch.setattr(commands,'respond',command);monkeypatch.setattr(webhook.line,'reply',reply)
    assert not webhook.deliver([event()])
    assert not webhook.deliver([event()])
    command.assert_called_once()
    assert all(call.args[1]==webhook.COMMAND_FAILED for call in reply.call_args_list)
