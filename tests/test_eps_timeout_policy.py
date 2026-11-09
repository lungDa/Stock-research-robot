import time
from datetime import date
from unittest.mock import Mock
import pytest,requests
from app.db import get,put
from app.providers import twse_eps as provider
from jobs import refresh_eps as job


def test_downloader_allows_slow_response_within_new_budget(monkeypatch):
    response=Mock(status_code=200)
    response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    response.iter_content.return_value=[b'%PDF-fixture']
    loader=Mock(return_value=response);monkeypatch.setattr(provider.requests,'get',loader)
    monkeypatch.setattr(provider.time,'monotonic',Mock(side_effect=[0,10]))
    parser=Mock(return_value={'rows':{}});monkeypatch.setattr(provider,'parse_pdf',parser)
    assert provider.fetch('2330.TW',date(2026,11,9))=={'rows':{}}
    assert loader.call_args.kwargs['timeout']==(8,12)
    assert loader.call_count==1 and parser.call_count==1


def test_total_stream_budget_remains_finite(monkeypatch):
    response=Mock(status_code=200)
    response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    response.iter_content.return_value=[b'%PDF-fixture']
    monkeypatch.setattr(provider.requests,'get',Mock(return_value=response))
    monkeypatch.setattr(provider.time,'monotonic',Mock(side_effect=[0,31]))
    parser=Mock();monkeypatch.setattr(provider,'parse_pdf',parser)
    with pytest.raises(requests.ReadTimeout):provider.fetch('2330.TW',date(2026,11,9))
    parser.assert_not_called()


def test_timeout_retries_later_without_repeating_request_on_same_run(monkeypatch):
    loader=Mock(side_effect=requests.ReadTimeout('private-token'))
    monkeypatch.setattr(job,'fetch',loader)
    put('eps:official:2330.TW',{'rows':{'2025':{'eps':66.26}}})
    assert job.run(['2330'])['state']=='failed'
    first=get('eps:state:2330.TW')
    assert 298<=first['next_attempt']-time.time()<=300
    assert first['transient_failures']==1 and 'private-token' not in str(first)
    assert job.run(['2330'])['eps_requests']==0 and loader.call_count==1
    put('eps:state:2330.TW',{**first,'next_attempt':0})
    job.run(['2330'])
    second=get('eps:state:2330.TW')
    assert 898<=second['next_attempt']-time.time()<=900
    assert loader.call_count==2
    assert get('eps:official:2330.TW')['rows']['2025']['eps']==66.26


def test_old_timeout_cooldown_migrates_once_and_success_resets_failures(monkeypatch):
    put('eps:state:2330.TW',{'status':'failed','error_code':'timeout','next_attempt':time.time()+86400})
    loader=Mock(return_value={'rows':{'2025':{'eps':66.26}},'report_date':'2026-11-09'})
    monkeypatch.setattr(job,'fetch',loader)
    assert job.run(['2330'])['state']=='updated'
    state=get('eps:state:2330.TW')
    assert state['policy_version']==job.POLICY_VERSION and state['transient_failures']==0
    assert job.run(['2330'])['eps_requests']==0
    assert loader.call_count==1


@pytest.mark.parametrize('code',['contract','http_403','http_429'])
def test_migration_never_bypasses_format_or_rejection_cooldowns(monkeypatch,code):
    put('eps:state:2330.TW',{'status':'failed','error_code':code,'next_attempt':time.time()+86400})
    loader=Mock();monkeypatch.setattr(job,'fetch',loader)
    assert job.run(['2330'])['eps_requests']==0
    loader.assert_not_called()


def test_new_contract_failure_still_retains_long_cooldown(monkeypatch):
    monkeypatch.setattr(job,'fetch',Mock(side_effect=ValueError('Company identity mismatch')))
    job.run(['2330'])
    state=get('eps:state:2330.TW')
    assert state['error_code']=='contract' and state['transient_failures']==0
    assert state['next_attempt']-time.time()>86000
