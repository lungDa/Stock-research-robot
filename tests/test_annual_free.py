from datetime import date
from unittest.mock import Mock
import pytest
from app.providers.annual_free import TW_DATASETS, SEC_CONCEPTS, taiwan_rows, sec_records, us_rows
from app.db import get,put
from app.services.multifactor import annual_rows,rated_many
TODAY=date(2026,11,9)


def rec(day,tag,value):
    return {'date':day,'stock_id':'2330','type':tag,'value':value}


def test_tw_cashflow_annual_not_sum_quarters_and_roe():
    income=[rec(f'2025-{d}',tag,v) for d in ('03-31','06-30','09-30','12-31')
            for tag,v in [('IncomeAfterTaxes',20),('Revenue',100),('EPS',5)]]
    feeds={TW_DATASETS[0]:income,TW_DATASETS[1]:[rec('2024-12-31','Equity',100),rec('2025-12-31','Equity',300)],
        TW_DATASETS[2]:[rec('2025-03-31','CashFlowsFromOperatingActivities',10),
                       rec('2025-12-31','CashFlowsFromOperatingActivities',50),
                       rec('2025-12-31','PropertyAndPlantAndEquipment',-20)]}
    r=taiwan_rows('2330.TW',feeds,TODAY)['2025']
    assert r['operating_cash_flow']==50 and r['capital_expenditure']==20
    assert r['roe_pct']==40 and r['revenue']==400
    assert 'eps' not in r and 'cash_dividends_paid' not in r


def dividend(day,value=2):
    return {'stock_id':'2330','CashDividendPaymentDate':day,'CashEarningsDistribution':value,
        'CashStatutorySurplus':0,'CashExDividendTradingDate':day,'year':'test'}


def test_paid_year_future_and_duplicate_dividends():
    ds=[dividend('2025-01-16'),dividend('2025-01-16'),dividend('2025-12-01',3),dividend('2027-01-01',99)]
    feeds={TW_DATASETS[3]:ds,TW_DATASETS[4]:[{'stock_id':'2330','date':'2025-12-31','close':100}]}
    rows=taiwan_rows('2330.TW',feeds,TODAY)
    assert rows['2025']['cash_dividend_per_share']==5
    assert rows['2025']['cash_yield_pct']==5 and '2027' not in rows
    assert '2024' not in rows  # missing distribution year is not zero


def test_conflicting_financial_duplicate_is_missing():
    feeds={TW_DATASETS[2]:[rec('2025-12-31','CashFlowsFromOperatingActivities',10),rec('2025-12-31','CashFlowsFromOperatingActivities',11)]}
    assert not taiwan_rows('2330.TW',feeds,TODAY)


def test_sec_only_annual_windows_latest_restatement_and_unit():
    payload={'tag':'EarningsPerShareDiluted','taxonomy':'us-gaap','units':{'USD/shares':[
        {'start':'2025-01-01','end':'2025-12-31','filed':'2026-02-01','val':2,'form':'10-K'},
        {'start':'2025-10-01','end':'2025-12-31','filed':'2026-02-01','val':1,'form':'10-K'},
        {'start':'2025-01-01','end':'2025-12-31','filed':'2026-03-01','val':3,'form':'10-K/A'},
        {'start':'2025-01-01','end':'2025-12-31','filed':'2027-03-01','val':99,'form':'10-K'}],
        'EUR/shares':[{'val':999}]}}
    records=sec_records(payload,'eps',TODAY)
    assert records['2025-12-31']['value']==3
    r=us_rows('0000000001',{'eps':records},TODAY)['2025']
    assert r['eps']==3 and r['currency']=='USD'


def test_declared_dividend_not_paid_or_streak():
    d={'value':2,'start':'2025-01-01','end':'2025-12-31','filed':'2026-02-01'}
    rows=us_rows('1',{'eps':{'2025-12-31':d},'cash_dividend_per_share':{'2025-12-31':d}},TODAY)
    assert rows['2025']['declared_dividend_per_share']==2
    assert 'cash_dividend_per_share' not in rows['2025']


def test_annual_shared_private_precedence_and_batching():
    put('annual:shared:AAPL',{'rows':{'2025':{'eps':2,'revenue':5,'provenance':'SEC_10K'}}})
    put('annual:Ualice:AAPL',{'2025':{'eps':8,'provenance':'user_import'}})
    assert annual_rows('Ualice','AAPL')['2025']['eps']==8
    assert annual_rows('Ubob','AAPL')['2025']['eps']==2
    assert annual_rows('Ualice','AAPL')['2025']['revenue']==5
    # 93 keys are split into bounded database batches instead of raising.
    assert len(rated_many([{'symbol':f'S{i}','kind':'UNKNOWN'} for i in range(30)],'public'))==30


def test_no_credentials_no_requests(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.delenv('FINMIND_TOKEN',raising=False);monkeypatch.delenv('SEC_USER_AGENT',raising=False)
    monkeypatch.setenv('ANNUAL_SYMBOLS','2330.TW,AAPL')
    loader=Mock(side_effect=AssertionError('must not download'));monkeypatch.setattr(job,'fetch_json',loader)
    job.run();loader.assert_not_called()


def test_worker_bounded_requests_token_only_header_and_cache(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','test-token');monkeypatch.setenv('ANNUAL_SYMBOLS','2330.TW,2412.TW')
    monkeypatch.delenv('SEC_USER_AGENT',raising=False)
    calls=[]
    def loader(url,params=None,**kw):
        calls.append((url,params,kw));return {'status':200,'data':[]}
    monkeypatch.setattr(job,'fetch_json',loader)
    job.run()
    assert len(calls)==8
    assert all('token' not in c[1] and c[2]['headers']['Authorization']=='Bearer test-token' for c in calls)
    assert all(c[2]['max_bytes']==1048576 and c[2]['seconds']==6 for c in calls)
    job.run();assert len(calls)==10
    job.run();assert len(calls)==10  # all feeds cooling


def test_worker_failure_preserves_previous_feed(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','x');monkeypatch.setenv('ANNUAL_SYMBOLS','2330.TW')
    key='annual:feed:2330.TW:'+TW_DATASETS[0]
    put(key,{'records':[rec('2025-03-31','Revenue',10)]})
    monkeypatch.setattr(job,'fetch_json',Mock(side_effect=RuntimeError('secret must not be logged')))
    job.run()
    assert get(key)['records'][0]['value']==10
    assert get(key)['next_attempt']>0


def test_fund_profile_payment_window_and_missing_not_zero():
    from app.providers.annual_free import taiwan_fund_profile
    events=[dividend('2026-01-01',2),dividend('2026-01-01',2),dividend('2026-12-01',99),dividend('2025-01-01',9)]
    r=taiwan_fund_profile('2330.TW',events,TODAY)
    assert r['cash_paid_365d_per_share']==2
    assert taiwan_fund_profile('0050.TW',events,TODAY)=={}


def test_paid_cash_total_supports_streak_but_declared_does_not():
    from app.services.multifactor import value_for
    rows={str(y):{'cash_dividends_paid':100} for y in range(2016,2026)}
    assert value_for({},rows,'dividend_streak',10,TODAY)==10
    rows['2020']={'declared_dividend_per_share':99}
    assert value_for({},rows,'dividend_streak',10,TODAY) is None


def test_taiwan_etf_cached_profile_not_company_rules():
    from app.services.multifactor import rated
    from app.services.freshness import local_now
    today=local_now().date().isoformat()
    put('annual:shared:0050.TW',{'rows':{},'fund_profile':{'as_of':today,'cash_paid_365d_per_share':3}})
    r=rated({'symbol':'0050.TW','kind':'ETF','price':100,'date':today},'public')
    assert r['yield']==3 and r['yield_basis']=='trailing_paid_365d'
    assert not any(c['metric']=='eps_latest' for c in r['rating']['checks'])


def test_source_throttle_stops_all_finmind_tasks(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('FINMIND_TOKEN','x');monkeypatch.setenv('ANNUAL_SYMBOLS','2330.TW,2412.TW')
    loader=Mock(return_value={'status':429,'data':[]})
    monkeypatch.setattr(job,'fetch_json',loader)
    job.run();assert loader.call_count==1
    job.run();assert loader.call_count==1


def test_sec_worker_declares_contact_and_populates_shared_rows(monkeypatch):
    import jobs.refresh_annual as job
    monkeypatch.setenv('SEC_USER_AGENT','StockLighthouse test@example.com')
    monkeypatch.setenv('ANNUAL_SYMBOLS','AAPL');monkeypatch.delenv('FINMIND_TOKEN',raising=False)
    calls=[]
    def load(url,params=None,**kw):
        calls.append((url,kw))
        if 'company_tickers' in url:return {'0':{'ticker':'AAPL','cik_str':320193}}
        tag=url.rsplit('/',1)[-1].replace('.json','')
        unit='USD/shares' if 'PerShare' in tag else 'USD'
        return {'cik':320193,'taxonomy':'us-gaap','tag':tag,'units':{unit:[
            {'val':5,'start':'2024-09-29','end':'2025-09-27','filed':'2025-11-01','form':'10-K'}]}}
    monkeypatch.setattr(job,'fetch_json',load)
    job.run()
    assert len(calls)==8 and all(c[1]['headers']['User-Agent'].endswith('test@example.com') for c in calls)
    rows=get('annual:shared:AAPL')['rows']
    assert rows['2025']['eps']==5 and rows['2025']['currency']=='USD'
    assert 'cash_dividend_per_share' not in rows['2025']


def test_sec_mismatched_period_does_not_combine():
    a={'value':5,'start':'2025-01-01','end':'2025-12-31','filed':'2026-02-01'}
    b={**a,'start':'2024-12-01'}
    rows=us_rows('1',{'eps':{'2025-12-31':a},'revenue':{'2025-12-31':b}},TODAY)
    assert 'revenue' not in rows['2025']
