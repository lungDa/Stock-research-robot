import time
from unittest.mock import Mock
from app.db import get,put
from app.services.query_fundamentals import prepare
from app.providers.annual_free import TW_DATASETS


def test_unconfigured_reports_no_download_or_queue(monkeypatch):
    monkeypatch.delenv('FINMIND_TOKEN',raising=False)
    assert prepare('2412')['state']=='not_configured'
    assert get('annual:requested') is None


def test_query_targets_symbol_without_watch_and_preserves_global_cursor(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','fake')
    put('annual:cursor',{'value':77})
    calls=[]
    def load(url,params=None,**kwargs):
        calls.append(params)
        return {'status':200,'data':[{'stock_id':'2412','date':'2025-12-31','type':'Equity','value':100}]}
    monkeypatch.setattr(job,'fetch_json',load)
    result=prepare('2412')
    assert result['annual_requests']<=2 and result['state']=='partial'
    assert calls and all(p['data_id']=='2412' for p in calls)
    assert '2412.TW' in get('annual:requested')
    assert get('annual:cursor')['value']==77
    assert prepare('2412')['state']=='cached'


def test_valid_shared_feeds_avoid_download(monkeypatch):
    monkeypatch.setenv('FINMIND_TOKEN','fake')
    for feed in TW_DATASETS:
        put('annual:feed:2412.TW:'+feed,{'status':'ok','records':[{'x':1}],'next_attempt':time.time()+86400})
    assert prepare('2412')['state']=='cached'


def test_source_cooldown_skips_requests(monkeypatch):
    monkeypatch.setenv('FINMIND_TOKEN','fake')
    put('annual:source:finmind',{'next_attempt':time.time()+86400})
    assert prepare('2412')['state']=='cooldown'


def test_failed_batch_not_reported_as_success(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','fake')
    monkeypatch.setattr(job,'run',Mock(return_value={'annual_requests':1,'updated_symbols':0,'failed_feeds':1}))
    assert prepare('2412')['state']=='failed'


def test_public_private_endpoint_paths_use_same_guard(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api.server import app
    monkeypatch.delenv('FINMIND_TOKEN',raising=False)
    with TestClient(app) as client:
        assert client.post('/fundamentals/prepare/2412').status_code==401
        r=client.post('/public/fundamentals/prepare/2412')
        assert r.status_code==200 and r.json()['state']=='not_configured'
        assert client.post('/public/fundamentals/prepare/bad*').status_code==400


def test_global_query_cap_bounds_distinct_symbols(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','fake')
    loader=Mock(return_value={'annual_requests':0,'updated_symbols':0,'failed_feeds':0})
    monkeypatch.setattr(job,'run',loader)
    prepare('2412');prepare('2330')
    assert prepare('2308')['state']=='limited' and loader.call_count==2


def test_daily_worker_includes_requested_symbols_not_in_watchlist(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','fake');monkeypatch.delenv('ANNUAL_SYMBOLS',raising=False)
    put('annual:requested',{'2412.TW':time.time()})
    params=[]
    def load(url,p=None,**kw):
        params.append(p);return {'status':200,'data':[{'stock_id':'2412','date':'2025-12-31','type':'Equity','value':1}]}
    monkeypatch.setattr(job,'fetch_json',load)
    job.run(max_requests=1)
    assert len(params)==1 and params[0]['data_id']=='2412'
