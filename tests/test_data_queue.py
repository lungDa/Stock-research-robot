import time
from unittest.mock import Mock
from app.db import put,get
from app.services.data_queue import enqueue,requested,source_slot
from app.services.query_fundamentals import request_download,process_download,status


def test_queue_bounded_no_user_watch_or_notification():
    from app.services.watchlist import watches,subscribed
    for n in range(100):assert enqueue(f'{1000+n}.TW')
    assert not enqueue('9999.TW') and len(requested())==100
    assert not watches('Ualice') and not subscribed()


def test_expired_queue_entries_cannot_hide_new_symbols():
    for n in range(100):put(f'annual:request:{1000+n}.TW',{'expires':1,'requested_at':1})
    assert enqueue('9999.TW')
    assert list(requested())==['9999.TW']


def test_legacy_requested_queue_is_read_without_reset():
    put('annual:requested',{'2412.TW':time.time(),'2330.TW':1})
    assert list(requested())==['2412.TW']


def test_source_day_budget_is_shared_and_bounded():
    assert source_slot('finmind',2) and source_slot('finmind',2)
    assert not source_slot('finmind',2)
    assert source_slot('sec',2)


def test_concurrent_budget_cannot_exceed_limit():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda _:source_slot('finmind',3),range(10)))
    assert sum(results)==3


def test_request_returns_before_network_and_deduplicates(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','fake')
    loader=Mock(side_effect=AssertionError('must enqueue only'));monkeypatch.setattr(job,'run',loader)
    assert request_download('2412')['state']=='queued'
    assert request_download('2412')['state']=='queued'
    assert len(requested())==1
    loader.assert_not_called()


def test_listed_eps_can_queue_without_finmind(monkeypatch):
    monkeypatch.delenv('FINMIND_TOKEN',raising=False)
    assert request_download('2412')['state']=='queued'
    assert request_download('6488.TWO')['state']=='queued'


def test_background_batch_stays_within_two_external_requests(monkeypatch):
    import jobs.refresh_tw_financials as official
    monkeypatch.setattr(official,'run',Mock(return_value={'official_requests':0,'state':'cached'}))
    import jobs.refresh_eps as eps
    import jobs.refresh_annual as annual
    monkeypatch.setattr(eps,'run',Mock(return_value={'eps_requests':1,'state':'updated'}))
    loader=Mock(return_value={'annual_requests':1,'updated_symbols':1,'failed_feeds':0})
    monkeypatch.setattr(annual,'run',loader)
    process_download('2412.TW')
    assert loader.call_args.kwargs['max_requests']==1
    assert status('2412')['state']=='partial'


def test_interrupted_immediate_batch_keeps_durable_request(monkeypatch):
    import jobs.refresh_tw_financials as official
    monkeypatch.setattr(official,'run',Mock(return_value={'official_requests':0,'state':'cached'}))
    import jobs.refresh_eps as eps
    monkeypatch.setenv('FINMIND_TOKEN','fake')
    request_download('2412')
    monkeypatch.setattr(eps,'run',Mock(side_effect=RuntimeError('provider')))
    process_download('2412.TW')
    assert status('2412')['state']=='failed' and '2412.TW' in requested()


def test_old_running_status_explains_scheduled_recovery():
    put('annual:query_result:2412.TW',{'state':'running','at':time.time()-360})
    result=status('2412')
    assert result['state']=='partial' and '排程' in result['message']


def test_request_endpoints_auth_and_public_background_processing(monkeypatch):
    import jobs.refresh_tw_financials as official
    monkeypatch.setattr(official,'run',Mock(return_value={'official_requests':0,'state':'cached'}))
    from fastapi.testclient import TestClient
    from app.api.server import app
    from app.services.watchlist import watches,subscribed
    import jobs.refresh_eps as eps
    import jobs.refresh_annual as annual
    monkeypatch.setenv('FINMIND_TOKEN','fake')
    monkeypatch.setattr(eps,'run',Mock(return_value={'eps_requests':0,'state':'cached'}))
    loader=Mock(return_value={'annual_requests':2,'updated_symbols':1,'failed_feeds':0})
    monkeypatch.setattr(annual,'run',loader)
    with TestClient(app) as client:
        assert client.post('/fundamentals/request/2412').status_code==401
        assert client.get('/fundamentals/status/2412').status_code==401
        response=client.post('/public/fundamentals/request/2412')
        assert response.status_code==200 and response.json()['state']=='queued'
        assert client.get('/public/fundamentals/status/2412').json()['state']=='partial'
        assert client.post('/public/fundamentals/request/bad*').status_code==400
    assert loader.call_count==1 and not watches('Ualice') and not subscribed()
