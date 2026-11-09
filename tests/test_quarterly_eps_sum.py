from datetime import date,timedelta
from unittest.mock import Mock
import time,copy
import pytest
from app.db import get,put
from app.providers.annual_free import TW_DATASETS
from app.providers.trailing import taiwan_eps_four_quarters,taiwan_trailing
from app.services.multifactor import rated,rated_many
from app.services.trailing_metrics import attach
from app.services.freshness import local_now

TODAY=date(2026,11,9)
DATES=['2025-12-31','2026-03-31','2026-06-30','2026-09-30']

def records(values=(1,2,3,4),dates=DATES):
    return [{'stock_id':'2330','date':day,'type':'EPS','value':value,'origin_name':'基本每股盈餘（元）'} for day,value in zip(dates,values)]


def test_sum_keeps_each_quarter_and_never_claims_verified_ttm():
    result=taiwan_eps_four_quarters('2330.TW',records(),TODAY)
    assert result['value']==10 and result['period_start']=='2025-10-01' and result['period_end']=='2026-09-30'
    assert result['calculation']['quarter_eps']==[1,2,3,4] and result['calculation']['quarter_ends']==DATES
    assert result['verified_share_basis'] is False and result['eps_type']=='four_quarter_sum'
    assert result['provenance']=='FinMind_quarterly_eps_sum' and result['unit']=='TWD_PER_SHARE'
    assert 'eps_ttm' not in taiwan_trailing('2330.TW',{TW_DATASETS[0]:records()},TODAY)


@pytest.mark.parametrize('values,total',[((0,0,0,0),0),((-1,-2,1,1),-1),((.1,.2,.3,.4),1)])
def test_zero_loss_and_decimals_are_real_values(values,total):
    assert taiwan_eps_four_quarters('2330.TW',records(values),TODAY)['value']==total


@pytest.mark.parametrize('rows',[
 records()[:-1],records()[1:],records()[:2]+records()[3:],
 records()+[{**records()[0],'value':99}],
 records()+[{'stock_id':'2330','date':'2026-12-31','type':'IncomeAfterTaxes','value':1}],
])
def test_missing_or_conflicting_quarters_remain_missing(rows):
    # A future record is ignored, while an actual latest quarter with missing EPS
    # blocks fallback to an older full window (tested separately below).
    if rows[-1].get('date')=='2026-12-31':assert taiwan_eps_four_quarters('2330.TW',rows,TODAY)['value']==10
    else:assert taiwan_eps_four_quarters('2330.TW',rows,TODAY) is None


def test_latest_reported_income_period_missing_eps_does_not_use_older_window():
    old_dates=['2025-09-30','2025-12-31','2026-03-31','2026-06-30']
    rows=records(dates=old_dates)+[{'stock_id':'2330','date':'2026-09-30','type':'Revenue','value':10}]
    assert taiwan_eps_four_quarters('2330.TW',rows,TODAY) is None


@pytest.mark.parametrize('value',[None,True,float('nan'),float('inf')])
def test_invalid_eps_is_not_zero(value):
    assert taiwan_eps_four_quarters('2330.TW',records((1,2,3,value)),TODAY) is None


def test_stale_semiannual_wrong_company_and_diluted_records_rejected():
    assert taiwan_eps_four_quarters('2412.TW',records(),TODAY) is None
    assert taiwan_eps_four_quarters('2330.TW',records(),date(2027,5,1)) is None
    assert taiwan_eps_four_quarters('2330.TW',records(dates=['2024-12-31','2025-06-30','2025-12-31','2026-06-30']),TODAY) is None
    diluted=records();diluted[-1]['origin_name']='稀釋每股盈餘'
    assert taiwan_eps_four_quarters('2330.TW',diluted,TODAY) is None
    assert taiwan_eps_four_quarters('2330.TW',records((1e308,1e308,1e308,1e308)),TODAY) is None


def test_duplicate_identical_record_not_counted_twice():
    assert taiwan_eps_four_quarters('2330.TW',records()+[records()[0]],TODAY)['value']==10


def test_selected_eps_sum_has_separate_basis_and_strict_private_value_keeps_priority():
    quarterly=taiwan_eps_four_quarters('2330.TW',records(),TODAY)
    quote={'symbol':'2330.TW','kind':'STOCK','currency':'TWD','price':100,'date':'2026-11-09','warnings':[]}
    shared={'trailing':{'eps_four_quarter_sum':quarterly}}
    result=attach(quote,shared,today=TODAY)
    assert result['eps']==10 and result['eps_basis']=='four_quarter_sum'
    assert 'eps_ttm' not in result['trailing_details']
    manual={'value':9,'period_start':'2025-10-01','period_end':'2026-09-30','source':'verified'}
    verified=attach(quote,shared,manual=manual,today=TODAY)
    assert verified['eps']==9 and verified['eps_basis']=='verified_or_reported_ttm'
    assert shared['trailing']['eps_four_quarter_sum']==quarterly


def quote():
    return {'symbol':'2330.TW','kind':'STOCK','currency':'TWD','price':100,'date':str(local_now().date()),'cached_at':time.time(),'warnings':[]}


def test_public_private_and_bulk_reads_use_same_sum_without_network_or_annual_override():
    put('annual:feed:2330.TW:'+TW_DATASETS[0],{'records':records()})
    put('annual:shared:2330.TW',{'rows':{'2025':{'eps':77,'currency':'TWD','provenance':'FinMind'}}})
    public=rated(quote(),'public');private=rated(quote(),'Ualice');bulk=rated_many([quote()],'Ualice')[0]
    for result in (public,private,bulk):
        assert result['eps']==10 and result['eps_basis']=='four_quarter_sum'
        assert result['income']['checks']['EPS為正'] is True
        assert result['annual_rows']['2025']['eps']==77
        assert result['data_quality']['current_fields'][0]['metric']=='eps_four_quarter_sum'
        assert result['data_quality']['current_fields'][0]['state']=='available'


def test_new_missing_quarter_invalidates_previously_cached_sum():
    previous=taiwan_eps_four_quarters('2330.TW',records(),TODAY)
    put('annual:shared:2330.TW',{'trailing':{'eps_four_quarter_sum':previous}})
    put('annual:feed:2330.TW:'+TW_DATASETS[0],{'records':records()[:-1]})
    result=rated(quote(),'public')
    assert result['eps'] is None and result['eps_basis'] is None


def test_worker_retains_eps_and_refills_recent_window_once_preserving_older_financials(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','fixture');monkeypatch.delenv('SEC_USER_AGENT',raising=False)
    key='annual:feed:2330.TW:'+TW_DATASETS[0]
    old={'stock_id':'2330','date':'2020-12-31','type':'Revenue','value':999}
    put(key,{'records':[old],'status':'ok','next_attempt':time.time()+7*86400})
    loader=Mock(return_value={'status':200,'data':records()})
    monkeypatch.setattr(job,'fetch_json',loader)
    result=job.run(['2330'],max_requests=1)
    assert result['annual_requests']==1 and get(key)['eps_schema']==job.TW_EPS_SCHEMA
    assert old in get(key)['records'] and len([r for r in get(key)['records'] if r['type']=='EPS'])==4
    params=loader.call_args.args[1]
    assert (date.fromisoformat(params['end_date'])-date.fromisoformat(params['start_date'])).days==730
    assert get('annual:shared:2330.TW')['trailing']['eps_four_quarter_sum']['value']==10
    put('annual:cursor',{'value':0})
    job.run(['2330'],max_requests=1)
    assert sum(call.args[1]['dataset']==TW_DATASETS[0] for call in loader.call_args_list)==1


def test_sum_warning_deduplicates_and_etf_does_not_use_company_eps():
    put('annual:feed:2330.TW:'+TW_DATASETS[0],{'records':records()})
    first=rated(quote(),'public');second=rated(first,'public')
    assert sum(w.startswith('EPS合計口徑：') for w in second['warnings'])==1
    fund=rated({**quote(),'kind':'ETF'},'public')
    assert fund['eps'] is None and fund['eps_basis'] is None


def test_ui_shows_quarterly_sum_period_method_and_positive_check(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from tests.test_improvements import quote as ui_quote
    import requests
    put('annual:feed:2330.TW:'+TW_DATASETS[0],{'records':records()})
    data=rated(ui_quote(),'public')
    def request(method,url,**kwargs):
        if '/quote/' in url:body=data
        elif '/fundamentals/request/' in url:body={'state':'cached','symbol':'2330.TW','message':'使用快取','feeds':[]}
        elif url.endswith('/scan'):body={}
        else:raise AssertionError('Unexpected request '+url)
        response=Mock(status_code=200);response.json.return_value=body;return response
    monkeypatch.setattr(requests,'request',request)
    app=AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py'),default_timeout=20)
    app.run();app.button(key='FormSubmitter:query-分析').click().run()
    assert not app.exception
    assert app.session_state['result']['eps_basis']=='four_quarter_sum'
    assert app.session_state['result']['income']['checks']['EPS為正'] is True
    assert any('未統一追溯調整股數基準' in item.value for item in app.caption)
    tables=[df.value for df in app.dataframe if hasattr(df.value,'columns') and '項目' in df.value.columns]
    assert any('EPS（近四季合計／元每股）' in list(table['項目']) for table in tables)


def test_migration_deferred_by_daily_budget_does_not_restore_old_week_cooldown(monkeypatch):
    import jobs.refresh_annual as job
    import app.services.data_queue as queue
    monkeypatch.setenv('FINMIND_TOKEN','fixture')
    key='annual:feed:2330.TW:'+TW_DATASETS[0]
    put(key,{'records':[{'stock_id':'2330','date':'2020-12-31','type':'Revenue','value':1}],
             'next_attempt':time.time()+7*86400,'status':'ok'})
    loader=Mock(return_value={'status':200,'data':records()})
    monkeypatch.setattr(job,'fetch_json',loader)
    monkeypatch.setattr(queue,'source_slot',lambda *a:False)
    job.run(['2330'],max_requests=1)
    assert get(key)['next_attempt']==0 and get(key)['pending_windows']
    loader.assert_not_called()
    monkeypatch.setattr(queue,'source_slot',lambda *a:True)
    put('annual:cursor',{'value':0})
    job.run(['2330'],max_requests=1)
    assert get(key)['records'][-1]['type']=='EPS' and loader.call_count==1
