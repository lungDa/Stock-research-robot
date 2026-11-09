import time
from datetime import date,timedelta
from unittest.mock import Mock
import pytest
from app.db import get,put
from app.providers.date_windows import split_window,covers
from app.providers.finmind_batch import batch,SourceRejected
from app.providers.bounded_http import ResourceLimitError
from app.providers.annual_free import TW_DATASETS,taiwan_rows

TODAY=date(2026,11,9)

def test_eps_typography_and_alias_conflict():
    from app.providers.fundamentals import parse
    from app.providers.taiwan_official import numeric
    row={'公司代號':'2412','出表日期':'1151101','年度':'114','季別':'4','基本每股盈餘 ( 元 )':'１２．５'}
    result=parse(row,'TW','eps','official',time.time())
    assert result[1]['fields']['eps']['value']==12.5
    row['基本每股盈餘（元）']='13'
    assert 'eps' not in parse(row,'TW','eps','official',time.time())[1]['fields']
    assert numeric('（１，２３４．５）')==-1234.5
    assert numeric('−3.2')==-3.2


def test_immediate_limit_still_queues_for_scheduled_worker(monkeypatch):
    from app.services.query_fundamentals import request_download
    from app.services.data_queue import requested
    from app.db import claim
    minute=str(int(time.time()//60))
    for i in range(2):claim('annual:query_minute:'+minute+':'+str(i),{'at':time.time()})
    result=request_download('2412')
    assert result['state']=='limited' and result['queued_for_schedule']
    assert '2412.TW' in requested()


def test_split_covers_exact_range_without_overlap():
    parts=split_window({'start':'2015-01-01','end':str(TODAY)})
    assert parts[0]['end']==str(TODAY) and parts[1]['start']=='2015-01-01'
    assert date.fromisoformat(parts[1]['end'])+timedelta(days=1)==date.fromisoformat(parts[0]['start'])
    assert covers(parts,'2015-01-01',str(TODAY))
    assert not covers(parts[:1],'2015-01-01',str(TODAY))


def test_oversize_is_saved_as_resumable_partition_not_failure():
    state={'records':[{'date':'2010-01-01','value':1}]}
    loader=Mock(side_effect=ResourceLimitError())
    result,changed=batch('2412.TW',TW_DATASETS[0],state,TODAY,loader,lambda *a:[],'secret')
    assert result['status']=='partial' and len(result['pending_windows'])==2
    assert result['records']==state['records'] and not changed
    assert loader.call_count==1 and result['next_attempt']>time.time()
    assert 'secret' not in str(result)


def test_resume_replaces_only_authoritative_window_and_completes_empty_tail():
    windows=[{'start':'2026-01-01','end':str(TODAY)},{'start':'2025-01-01','end':'2025-12-31'}]
    state={'pending_windows':windows,'records':[{'date':'2024-12-31','value':1},{'date':'2026-06-30','value':2}]}
    loader=Mock(return_value={'status':200,'data':[{'date':'2026-06-30','value':3}]})
    compact=lambda feed,rows,code:rows
    first,changed=batch('2412.TW',TW_DATASETS[0],state,TODAY,loader,compact,'token')
    assert changed and first['status']=='partial'
    assert [r['value'] for r in first['records']]==[1,3]
    loader.return_value={'status':200,'data':[]}
    final,changed=batch('2412.TW',TW_DATASETS[0],first,TODAY,loader,compact,'token')
    assert changed and final['status']=='ok' and not final['pending_windows']
    assert covers(final['coverage_windows'],'2025-01-01',str(TODAY))
    assert 'token' not in str(loader.call_args.args[1])
    assert loader.call_args.args[2]=={'Authorization':'Bearer token'}


@pytest.mark.parametrize('code',[400,401,403,429])
def test_source_rejection_keeps_status_for_correct_scope(code):
    with pytest.raises(SourceRejected) as error:
        batch('2412.TW',TW_DATASETS[0],{},TODAY,lambda *a:{'status':code},lambda *a:[],'')
    assert error.value.status==code


def test_dividend_coverage_allows_first_recent_payment_but_rejects_gap_or_old_coverage():
    from app.services.trailing_metrics import attach
    quote={'symbol':'2412.TW','kind':'STOCK','currency':'TWD','price':100,'date':'2026-11-06','warnings':[]}
    paid={'source':'verified fixture','currency':'TWD','fetched_at':time.time(),
          'payments':[{'date':'2026-08-01','amount':4}],
          'coverage_windows':[{'start':'2025-01-01','end':str(TODAY),'at':time.time()}]}
    assert attach(quote,{},paid,today=TODAY)['yield']==4
    paid['coverage_windows'][0]['start']='2026-01-01'
    assert attach(quote,{},paid,today=TODAY)['yield'] is None
    paid['coverage_windows'][0]={'start':'2025-01-01','end':str(TODAY),'at':time.time()-9*86400}
    assert attach(quote,{},paid,today=TODAY)['yield'] is None


def test_partial_calendar_dividends_do_not_appear_as_full_year():
    row={'stock_id':'2412','date':'2025-06-01','year':'2024','CashDividendPaymentDate':'2025-08-01',
         'CashEarningsDistribution':4,'CashStatutorySurplus':0}
    feeds={TW_DATASETS[3]:[row]}
    assert '2025' not in taiwan_rows('2412.TW',feeds,TODAY,{TW_DATASETS[3]:[{'start':'2025-06-01','end':'2025-12-31'}]})
    result=taiwan_rows('2412.TW',feeds,TODAY,{TW_DATASETS[3]:[{'start':'2025-01-01','end':'2025-12-31'}]})
    assert result['2025']['cash_dividend_per_share']==4


@pytest.mark.parametrize('index',[2,2.0,'2'])
def test_mops_verified_code_name_alias_and_integral_axis(index):
    from app.providers.mopsfin import parse_annual
    body={'ylabel':'元','xaxisList':['2023Q4','2024Q4','2025Q4'],
          'graphData':[{'label':'環球晶','data':[[index,4.5]]}],
          'displayCompanyId':['6488'],'checkedNameList':['環球晶'],'extraNameList':[]}
    assert parse_annual(body,'6488.TWO','eps','6488 環球晶',TODAY)['2025']['eps']==4.5
    body['displayCompanyId']=['2330']
    with pytest.raises(ValueError):parse_annual(body,'6488.TWO','eps','6488 環球晶',TODAY)


def test_history_replenishment_advances_past_current_month(monkeypatch):
    import jobs.refresh_history as job
    from app.services.data_queue import enqueue
    enqueue('2412.TW');calls=[]
    today=job.datetime.now(job.ZoneInfo('Asia/Taipei')).date()
    def load(code,market,first,today):
        calls.append(first)
        put(f'official:month:{market}:{code}:{first:%Y%m}',{'at':time.time(),'data':[]})
    monkeypatch.setattr(job,'month',load)
    for _ in range(4):assert job.run()['attempted']<=2
    assert calls==job.months(today)
    assert job.run()['attempted']==0


def test_new_month_cache_updates_technicals_without_refreshing_price_time():
    from app.providers.taiwan_official import refresh_cached_history
    from jobs.refresh_history import months
    from app.services.freshness import local_now
    today=local_now().date();plan=months(today)
    rows=[{'date':str(plan[-1]+timedelta(days=i)),'close':100.,'volume':1000.} for i in range((today-plan[-1]).days+1) if (plan[-1]+timedelta(days=i)).weekday()<5]
    for first in plan:
        put(f'official:month:TW:2412:{first:%Y%m}',{'at':time.time(),'data':[r for r in rows if r['date'][:7]==str(first)[:7]]})
    quote={'symbol':'2412.TW','price':100.,'date':rows[-1]['date'],'cached_at':123,'updated_at':'original','data_status':'stale','warnings':[]}
    result=refresh_cached_history(quote)
    assert result['ma60']==100 and result['history_count']>=60
    assert result['cached_at']==123 and result['updated_at']=='original' and result['data_status']=='stale'
    assert refresh_cached_history(result)==result


def test_scan_rejects_returned_stale_even_if_db_is_fresh(monkeypatch):
    import jobs.scan as job
    monkeypatch.setattr(job,'load',lambda:['2412.TW'])
    quote={'symbol':'2412.TW','price':100,'cached_at':time.time(),'date':str(job.local_now().date()),'name':'test'}
    put('quote:2412.TW',quote)
    monkeypatch.setattr(job,'research',lambda *a,**k:{**quote,'data_status':'stale'})
    with pytest.raises(RuntimeError):job.run(1)
    assert get('scan:last_failure')['fresh_count']==0


def test_annual_worker_resumes_oversized_feed_instead_of_one_day_failure(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','fixture-token')
    loader=Mock(side_effect=ResourceLimitError());monkeypatch.setattr(job,'fetch_json',loader)
    first=job.run(['2412.TW'],max_requests=1)
    key='annual:feed:2412.TW:'+TW_DATASETS[0]
    state=get(key)
    assert first['annual_requests']==1 and first['failed_feeds']==0
    assert state['status']=='partial' and len(state['pending_windows'])==2
    assert 0<state['next_attempt']-time.time()<=60
    assert get('annual:source:finmind') is None
    put(key,{**state,'next_attempt':0});put('annual:cursor',{'value':0})
    loader.side_effect=None
    loader.return_value={'status':200,'data':[{'stock_id':'2412','date':'2025-12-31','type':'Revenue','value':10}]}
    second=job.run(['2412.TW'],max_requests=1)
    assert second['annual_requests']==1 and get(key)['records'][0]['value']==10
    assert len(get(key)['pending_windows'])==1
    assert loader.call_args.args[1]['start_date']==state['pending_windows'][0]['start']


@pytest.mark.parametrize('code,global_cooldown',[(400,False),(429,True)])
def test_annual_worker_only_cools_all_symbols_for_source_wide_rejection(monkeypatch,code,global_cooldown):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','fixture-token')
    monkeypatch.setattr(job,'fetch_json',lambda *a,**k:{'status':code,'data':[]})
    result=job.run(['2412.TW'],max_requests=1)
    assert result['failed_feeds']==1
    assert bool(get('annual:source:finmind'))==global_cooldown


def test_query_status_exposes_saved_split_progress():
    from app.services.query_fundamentals import status
    put('annual:feed:2412.TW:'+TW_DATASETS[0],{'status':'partial','records':[{'date':'2025-12-31'}],
        'pending_windows':[{'start':'2020-01-01','end':'2024-12-31'}]})
    feed=status('2412')['feeds'][0]
    assert feed['state']=='partial' and feed['pending_windows']==1 and feed['downloaded_records']==1
