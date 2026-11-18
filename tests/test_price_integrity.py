"""Calendar and corporate-action scenarios; all source data is synthetic."""
import copy
from datetime import date, datetime, timedelta
from unittest.mock import Mock
import pytest
from app.db import get, put
from app.services.freshness import TAIPEI
from app.services import freshness
from app.services.trading_calendar import expected_close, status
from app.providers.corporate_actions import FEEDS, adjust, attach, compact


def calendar(year, closed=(), opened=()):
    return {'year':year,'closed':list(closed),'opened':list(opened)}


def reader(*calendars):
    docs={'recommendations:calendar:'+str(c['year']):c for c in calendars}
    return lambda k,d=None:docs.get(k,d)


def test_long_holiday_accepts_only_last_actual_session():
    closed=[str(date(2026,2,13)+timedelta(days=i)) for i in range(11)]
    read=reader(calendar(2026,closed))
    now=datetime(2026,2,23,12,tzinfo=TAIPEI)
    assert expected_close(now,read)==date(2026,2,12)
    assert status({'date':'2026-02-12'},now,read)['state']=='current'
    assert status({'date':'2026-02-11'},now,read)['state']=='outdated'


@pytest.mark.parametrize('hour,minute,expected',[(18,16,'2026-11-18'),(18,17,'2026-11-19')])
def test_daily_publication_cutoff(hour,minute,expected):
    now=datetime(2026,11,19,hour,minute,tzinfo=TAIPEI)
    assert str(expected_close(now,reader(calendar(2026))))==expected


def test_new_year_uses_prior_year_calendar_and_never_guesses():
    now=datetime(2027,1,1,19,tzinfo=TAIPEI)
    c=calendar(2027,['2027-01-01'])
    assert expected_close(now,reader(c)) is None
    assert expected_close(now,reader(c,calendar(2026)))==date(2026,12,31)


def test_emergency_closure_override_and_weekend_opening():
    docs={'recommendations:calendar:2026':calendar(2026,opened=['2026-11-21']),
          'recommendations:session_overrides':{'2026-11-19':False}}
    read=lambda k,d=None:docs.get(k,d)
    assert expected_close(datetime(2026,11,19,19,tzinfo=TAIPEI),read)==date(2026,11,18)
    assert expected_close(datetime(2026,11,22,12,tzinfo=TAIPEI),read)==date(2026,11,21)


def test_missing_calendar_blocks_ratings_without_network(monkeypatch):
    monkeypatch.setattr(freshness,'local_now',lambda:datetime(2026,11,19,19,tzinfo=TAIPEI))
    d={'symbol':'2330.TW','price':100,'date':'2026-11-19','cached_at':0}
    assert not freshness.market_usable(d)
    assert freshness.mark_cached(d)['freshness']['state']=='calendar_missing'


def test_calendar_qualifies_old_holiday_cache_without_rewriting_timestamps(monkeypatch):
    closed=[str(date(2026,2,13)+timedelta(days=i)) for i in range(11)]
    put('recommendations:calendar:2026',calendar(2026,closed))
    monkeypatch.setattr(freshness,'local_now',lambda:datetime(2026,2,23,12,tzinfo=TAIPEI))
    d={'symbol':'2330.TW','price':100,'date':'2026-02-12','cached_at':1,'updated_at':'original','data_status':'partial'}
    assert freshness.market_usable(d) and not freshness.quote_due(d)
    cached=freshness.mark_cached(d)
    assert cached['data_status']=='partial' and cached['cached_at']==1 and cached['updated_at']=='original'


def test_missing_one_session_and_future_quote_are_rejected(monkeypatch):
    put('recommendations:calendar:2026',calendar(2026))
    monkeypatch.setattr(freshness,'local_now',lambda:datetime(2026,11,19,19,tzinfo=TAIPEI))
    for day in ('2026-11-18','2026-11-20'):
        assert not freshness.market_usable({'symbol':'2330.TW','price':100,'date':day})


def rows():
    return [{'date':str(date(2026,8,1)+timedelta(days=i)),'close':100.,'volume':1000.} for i in range(80)]


def feeds(prices):
    return {f:{'status':'ok','events':[],'coverage_windows':[{'start':prices[0]['date'],'end':prices[-1]['date']}]} for f in FEEDS}


@pytest.mark.parametrize('before,after,feed',[(100,95,'TaiwanStockDividendResult'),
    (100,25,'TaiwanStockSplitPrice'),(100,500,'TaiwanStockSplitPrice'),
    (100,10,'TaiwanStockParValueChange'),(100,125,'TaiwanStockCapitalReductionReferencePrice')])
def test_dividend_split_reverse_split_and_par_changes_preserve_latest_raw_price(before,after,feed):
    prices=rows();event_day=prices[40]['date']
    for row in prices[40:]:row['close']=after
    source=feeds(prices);source[feed]['events']=[{'date':event_day,'before':before,'after':after,'feed':feed}]
    original=copy.deepcopy(prices)
    adjusted,events=adjust(prices,source,'2330.TW')
    assert prices==original
    assert [r['adjusted_close'] for r in adjusted]==pytest.approx([after]*80)
    assert adjusted[-1]['adjustment_factor']==1 and adjusted[-1]['close']==after
    assert adjusted[0]['volume']==1000


def test_multiple_events_compound_and_duplicate_source_is_not_double_applied():
    prices=rows()
    for row in prices[20:40]:row['close']=95
    for row in prices[40:]:row['close']=19
    source=feeds(prices)
    event={'date':prices[20]['date'],'before':100,'after':95}
    source['TaiwanStockDividendResult']['events']=[event]
    source['TaiwanStockSplitPrice']['events']=[event,{'date':prices[40]['date'],'before':95,'after':19}]
    adjusted,events=adjust(prices,source,'2330.TW')
    assert len(events)==2 and adjusted[0]['adjustment_factor']==pytest.approx(.19)
    assert [r['adjusted_close'] for r in adjusted]==pytest.approx([19]*80)


@pytest.mark.parametrize('fault',['missing_feed','coverage_gap','conflict','bad_preclose','missing_event_day','negative'])
def test_unverified_adjustments_never_produce_technicals(fault):
    prices=rows();source=feeds(prices);feed=list(FEEDS)[0]
    event={'date':prices[40]['date'],'before':100,'after':95}
    source[feed]['events']=[event]
    if fault=='missing_feed':source.pop(feed)
    if fault=='coverage_gap':source[feed]['coverage_windows'][0]['end']=prices[20]['date']
    if fault=='conflict':source[list(FEEDS)[1]]['events']=[{**event,'after':90}]
    if fault=='bad_preclose':event['before']=110
    if fault=='missing_event_day':prices.pop(40)
    if fault=='negative':event['after']=-1
    read=lambda k,d=None:source.get(k.rsplit(':',1)[-1],d)
    result=attach({'symbol':'2330.TW','price':prices[-1]['close'],'date':prices[-1]['date'],
                   'history':prices,'ma20':100,'ma60':100},read)
    assert result['adjustment_status']=='missing' and result['ma20'] is None and result['ma60'] is None
    assert result['price']==100


def test_compaction_uses_event_reference_and_identity():
    event={'stock_id':'2330','date':'2026-09-01','before_price':100,'after_price':95}
    result=compact('TaiwanStockDividendResult',[event],'2330.TW','2026-08-01','2026-10-01')
    assert result[0]['before']==100 and result[0]['after']==95
    with pytest.raises(ValueError):compact('TaiwanStockDividendResult',[{**event,'stock_id':'2317'}],'2330.TW','2026-08-01','2026-10-01')


def test_worker_resumes_all_four_feeds_with_shared_budget(monkeypatch):
    from jobs import refresh_corporate_actions as worker
    monkeypatch.setenv('FINMIND_TOKEN','test')
    loader=Mock(return_value={'status':200,'data':[]})
    monkeypatch.setattr(worker,'fetch_json',loader)
    assert worker.run(['2330.TW'])['action_requests']==2
    assert worker.run(['2330.TW'])['action_requests']==2
    assert worker.run(['2330.TW'])['action_requests']==0
    assert {c.args[1]['dataset'] for c in loader.call_args_list}==set(FEEDS)
    assert all(c.args[1]['data_id']=='2330' for c in loader.call_args_list)
    assert 'TaiwanStockPriceAdj' not in str(loader.call_args_list)


def test_failed_refresh_does_not_extend_coverage_or_erase_success(monkeypatch):
    from jobs import refresh_corporate_actions as worker
    monkeypatch.setenv('FINMIND_TOKEN','test')
    key='corporate:feed:2330.TW:'+next(iter(FEEDS))
    old={'status':'ok','events':[],'coverage_windows':[{'start':'2026-01-01','end':'2026-02-01'}]}
    put(key,old)
    monkeypatch.setattr(worker,'fetch_json',Mock(side_effect=TimeoutError()))
    worker.run(['2330.TW'],max_requests=1)
    assert get(key)['coverage_windows']==old['coverage_windows']


def test_attach_is_idempotent_and_refuses_incomplete_history():
    prices=rows();source=feeds(prices);read=lambda k,d=None:source.get(k.rsplit(':',1)[-1],d)
    raw={'symbol':'2330.TW','date':prices[-1]['date'],'price':100,'history':prices}
    first=attach(raw,read);second=attach(first,read)
    assert first==second and first['ma60']==100
    assert attach({**raw,'technical_history_incomplete':True},read)['ma60'] is None


def test_query_ratings_and_market_collection_share_adjusted_averages(monkeypatch):
    from app.providers.taiwan_official import build_result
    from app.services.multifactor import rated_many
    from app.services.market_recommendations import collect
    from app.services.analysis import enrich
    import time
    prices=rows()
    for row in prices[40:]:row['close']=25
    prices[-1]['close']=26
    source=feeds(prices)
    source['TaiwanStockSplitPrice']['events']=[{'date':prices[40]['date'],'before':100,'after':25}]
    for feed,state in source.items():put('corporate:feed:2330.TW:'+feed,state)
    now=datetime.fromisoformat(prices[-1]['date']).replace(hour=19,tzinfo=TAIPEI)
    monkeypatch.setattr(freshness,'local_now',lambda:now)
    monkeypatch.setattr('app.services.multifactor.local_now',lambda:now)
    put('recommendations:calendar:2026',calendar(2026))
    raw=build_result('2330.TW',prices,{'name':'sample','kind':'STOCK'},[])
    raw['cached_at']=time.time()
    query=enrich(raw)
    bulk=rated_many([raw],'public')[0]
    put('quote:2330.TW',raw)
    snapshots={'TW':{'2330':{'date':raw['date'],'close':26,'name':'sample'}}}
    result,_=collect(['2330.TW'],snapshots,now.date(),'public',time.monotonic()+10)
    for item in (query,bulk,result[0][0]):
        assert item['price']==26 and item['adjusted_close']==26
        assert item['ma20']==pytest.approx(25.05) and item['adjustment_status']=='verified'
        assert item['history'][0]['close']==100


def test_before_close_rejects_same_day_and_after_close_accepts_verified_daily_bar():
    read=reader(calendar(2026))
    before=datetime(2026,11,19,13,29,tzinfo=TAIPEI)
    after=before.replace(minute=30)
    assert status({'date':'2026-11-19'},before,read)['state']=='outdated'
    assert status({'date':'2026-11-19'},after,read)['state']=='current'
