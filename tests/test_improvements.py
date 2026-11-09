import copy,time
from datetime import timedelta
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.db import get,put,acquire_lease,release_lease
from app.api.server import app
from app.services.freshness import local_now
from app.services.multifactor import DEFAULT,rule,evaluate,rated,rated_many,annual_rows


def quote(symbol='2330.TW'):
    return {'symbol':symbol,'name':'測試','kind':'STOCK','currency':'TWD','price':110,
        'date':str(local_now().date()),'cached_at':time.time(),'adjusted_close':110,
        'ma20':100,'ma60':90,'volume_ratio':1,'volatility':10,'history':[],
        'data_status':'available','warnings':[],'source':'fixture'}


def test_required_missing_blocks_buy_in_available_mode():
    c=copy.deepcopy(DEFAULT);c['missing_policy']='available'
    c['stock_rules']=[rule('eps_latest',1,1),rule('roe_avg',15,5)]
    rows={str(local_now().year-1):{'eps':3}}
    result=evaluate(quote(),c,rows)
    assert result['score']==100 and result['coverage']==50
    assert result['grade']=='資料不足' and result['required_missing']


@pytest.mark.parametrize('change',[{'data_status':'stale'},{'data_status':'fundamentals_only'},
    {'price':None},{'date':'2000-01-01'},{'date':'2099-01-01'}])
def test_annual_only_cannot_emit_buy_with_unusable_market(change):
    c=copy.deepcopy(DEFAULT);c['stock_rules']=[rule('eps_latest',1,1)]
    result=evaluate({**quote(),**change},c,{str(local_now().year-1):{'eps':3}})
    assert result['grade']=='資料不足' and not result['market_usable']


def test_optional_missing_still_allows_capped_buy():
    c=copy.deepcopy(DEFAULT);c['missing_policy']='available'
    c['stock_rules']=[rule('eps_latest',1,1),rule('ma20_ma60',0,1,required=False)]
    result=evaluate({**quote(),'ma60':None},c,{str(local_now().year-1):{'eps':3}})
    assert result['grade']=='買'


def test_public_expired_cache_refreshes(monkeypatch):
    import app.api.public as api
    old={**quote(),'cached_at':time.time()-40*3600,'data_status':'stale'}
    refresh=Mock(return_value=quote())
    monkeypatch.setattr(api,'cached_quote',lambda s:old)
    monkeypatch.setattr(api,'research',refresh)
    with TestClient(app) as c:
        response=c.get('/public/quote/2330')
    assert response.status_code==200 and response.json()['price']==110
    refresh.assert_called_once_with('2330.TW')


def test_public_fresh_cache_avoids_provider(monkeypatch):
    import app.api.public as api
    monkeypatch.setattr(api,'cached_quote',lambda s:quote())
    loader=Mock(side_effect=AssertionError('unexpected network'));monkeypatch.setattr(api,'research',loader)
    with TestClient(app) as c:assert c.get('/public/quote/2330').status_code==200
    loader.assert_not_called()


def test_public_limit_preserves_old_data_and_timestamp(monkeypatch):
    import app.api.public as api
    old={**quote(),'cached_at':time.time()-40*3600}
    monkeypatch.setattr(api,'cached_quote',lambda s:old)
    monkeypatch.setattr(api,'reserve_refresh',lambda:False)
    with TestClient(app) as c:result=c.get('/public/quote/2330').json()
    assert result['cached_at']==old['cached_at'] and result['refresh_deferred']
    assert result['data_status']=='stale' and result['rating']['grade']=='資料不足'


def test_refresh_failure_retains_stale_cache(monkeypatch):
    import app.services.research as research
    old={**quote(),'cached_at':time.time()-2*3600,'price_basis':'未還原收盤價'}
    put('quote:2330.TW',old)
    monkeypatch.setattr(research,'fetch',Mock(side_effect=TimeoutError()))
    result=research.research('2330')
    assert result['cached_at']==old['cached_at'] and result['data_status']=='stale'
    assert rated(result,'public')['rating']['grade']=='資料不足'


def test_batch_and_single_use_same_data_and_grade():
    data=quote();put('quote:2330.TW',data)
    put('eps:official:2330.TW',{'rows':{str(local_now().year-1):{'eps':4,'as_of':str(local_now().date()),'source_url':'https://www.twse.com.tw/'}}})
    single=rated(data,'Ualice');batch=rated_many([data],'Ualice')[0]
    assert single==batch


def test_shared_us_cache_visible_in_personal_ratings():
    from app.services.watchlist import add
    from app.services.assistant import personal_ratings
    add('Ualice','AAPL');put('usdaily:quote:AAPL',{**quote('AAPL'),'currency':'USD'})
    result=personal_ratings('Ualice')
    assert len(result)==1 and result[0]['price']==110


def test_quality_explains_ttm_and_unsupported_dividend_source():
    result=rated({**quote('MSFT'),'currency':'USD'},'public')
    current={r['metric']:r for r in result['data_quality']['current_fields']}
    assert current['eps_ttm']['state']=='verification_required'
    assert current['paid_yield_pct']['state']=='unsupported'


def test_eps_snapshot_does_not_overwrite_private_value_or_provenance():
    put('eps:official:2330.TW',{'rows':{'2025':{'eps':5,'as_of':'2026-11-09','source_url':'https://www.twse.com.tw/','provenance':'TWSE_company_profile'}}})
    put('annual:Ualice:2330.TW',{'2025':{'eps':6,'source_url':'https://example.com/report','provenance':'user_import'}})
    row=annual_rows('Ualice','2330.TW')['2025']
    assert row['eps']==6 and row['field_sources']['eps']['provenance']=='user_import'
    assert annual_rows('Ubob','2330.TW')['2025']['eps']==5


def test_lease_exclusion_expiry_and_old_owner_cannot_unlock(monkeypatch):
    import app.db as db
    owner=acquire_lease('worker',10)
    assert owner and acquire_lease('worker',10) is None
    now=time.time();monkeypatch.setattr(time,'time',lambda:now+11)
    newer=acquire_lease('worker',10);assert newer and newer!=owner
    release_lease('worker',owner)
    assert acquire_lease('worker',10) is None
    release_lease('worker',newer)
    assert acquire_lease('worker',10)


def test_annual_worker_busy_makes_no_external_request(monkeypatch):
    import jobs.refresh_annual as job
    owner=acquire_lease('annual:worker')
    loader=Mock();monkeypatch.setattr(job,'fetch_json',loader)
    assert job.run(['2330.TW'])['state']=='busy'
    loader.assert_not_called();release_lease('annual:worker',owner)


def test_admin_status_explicit_allowlist_and_no_secrets(monkeypatch):
    from tests.test_api import A,B
    monkeypatch.setenv('ADMIN_LINE_USER_IDS','Ualice')
    monkeypatch.setenv('FINMIND_TOKEN','private-never-return')
    with TestClient(app) as c:
        assert c.get('/admin/status').status_code==401
        assert c.get('/admin/status',headers=B).status_code==403
        response=c.get('/admin/status',headers=A)
        assert response.status_code==200 and response.json()['database']=='ok'
        assert 'private-never-return' not in response.text and 'Ualice' not in response.text
        assert c.get('/ready').status_code==200


def test_retention_deletes_ephemeral_but_preserves_finances():
    from jobs.maintenance import run
    now=time.time()
    put('auth:session:expired',{'expires':now-2*86400})
    put('auth:session:active',{'expires':now+3600})
    put('event:old',{'at':now-31*86400})
    put('annual:shared:2330.TW',{'at':1,'rows':{'2025':{'eps':5}}})
    put('member:Ualice',{'at':1,'active':True})
    put('strategy:Ualice',{'at':1,'saved':True})
    result=run()
    assert result['deleted']==2
    assert get('auth:session:expired') is None and get('event:old') is None
    assert get('auth:session:active') and get('annual:shared:2330.TW') and get('member:Ualice') and get('strategy:Ualice')


def test_rolling_paid_yield_recomputed_from_events_for_etf():
    from app.services.trailing_metrics import attach
    today=local_now().date();cut=today-timedelta(days=365)
    shared={'fund_profile':{'as_of':str(today-timedelta(days=2)),'fetched_at':time.time()-86400,
        'currency':'TWD','payments':[{'date':str(cut-timedelta(days=30)),'amount':1},
        {'date':str(cut),'amount':2},{'date':str(today-timedelta(days=30)),'amount':3}]}}
    result=attach({**quote(),'kind':'ETF','price':100},shared)
    assert result['yield']==3 and result['yield_basis']=='trailing_paid_365d'
    assert result['trailing_details']['paid_yield_pct']['period_end']==str(today)
    assert attach({**quote(),'kind':'ETF','price':200},shared)['yield']==1.5


def test_rebuilding_old_dividend_feed_does_not_make_it_fresh():
    from app.services.trailing_metrics import attach
    today=local_now().date()
    shared={'fund_profile':{'as_of':str(today),'fetched_at':time.time()-9*86400,'currency':'TWD',
        'payments':[{'date':str(today-timedelta(days=400)),'amount':1},{'date':str(today-timedelta(days=5)),'amount':2}]}}
    assert attach(quote(),shared)['yield'] is None


def test_cached_paid_percentage_never_reused_without_current_events():
    from app.services.trailing_metrics import attach
    shared={'trailing':{'paid_yield_pct':{'value':99,'period_end':'2020-01-01'}}}
    assert attach(quote(),shared)['yield'] is None


def test_retention_cursors_eventually_reach_expired_rows():
    from jobs.maintenance import run
    now=time.time()
    put('event:aaa',{'at':now});put('event:zzz',{'at':now-31*86400})
    run(batch_size=1);assert get('event:zzz')
    run(batch_size=1);assert get('event:zzz') is None and get('event:aaa')


def test_lease_only_one_concurrent_worker_wins():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as pool:
        owners=list(pool.map(lambda _:acquire_lease('concurrent',20),range(5)))
    assert sum(owner is not None for owner in owners)==1


def test_quality_reads_batched_queue_state_consistently(monkeypatch):
    monkeypatch.setenv('FINMIND_TOKEN','fake')
    put('annual:query_result:2330.TW',{'state':'queued','at':time.time()})
    one=rated(quote(),'public');many=rated_many([quote()],'public')[0]
    assert one['data_quality']==many['data_quality']
    assert any(r['state']=='queued' for r in one['data_quality']['rule_fields'])
