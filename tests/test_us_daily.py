from datetime import date,timedelta
import time
from unittest.mock import Mock
import pytest
from app.db import put,get
from app.providers.us_daily import parse
from app.services.research import research,cached_quote
TODAY=date(2026,11,9)


def records(n=70,adjusted=True):
    return [{'stock_id':'AAPL','date':str(TODAY-timedelta(days=n-i)),
             'Close':100+i,'Adj_Close':90+i if adjusted else None,'Volume':1000} for i in range(n)]


def test_daily_price_basis_and_no_invented_financials():
    r=parse('AAPL',records(),TODAY,{'kind':'STOCK'})
    assert r['price']==169 and r['adjusted_close']==159 and r['kind']=='STOCK'
    assert r['ma20']==pytest.approx(149.5) and r['yield'] is None
    assert r['source']=='FinMind / USStockPrice'


def test_missing_adjusted_prices_do_not_generate_technical_signals():
    r=parse('AAPL',records(adjusted=False),TODAY)
    assert r['ma20'] is None and r['volatility'] is None and r['kind']=='UNKNOWN'
    assert r['swing']['checks']['站上20日均線'] is None


def test_malformed_stale_and_wrong_symbol_rejected():
    with pytest.raises(ValueError):parse('MSFT',records(),TODAY)
    with pytest.raises(ValueError):parse('AAPL',records(3),TODAY)
    with pytest.raises(ValueError):parse('AAPL',records(),TODAY+timedelta(days=30))


def test_shared_cache_skips_yahoo(monkeypatch):
    import app.services.research as svc
    from app.services.freshness import local_now
    r=parse('AAPL',records(),TODAY,{'kind':'STOCK'})
    r.update(date=str(local_now().date()),cached_at=time.time())
    put('usdaily:quote:AAPL',r)
    fail=Mock(side_effect=AssertionError('must not call Yahoo'));monkeypatch.setattr(svc,'fetch',fail)
    assert research('AAPL')['price']==169 and cached_quote('AAPL')['price']==169
    fail.assert_not_called()


def test_yahoo_failure_keeps_sec_fundamentals_without_fake_price(monkeypatch):
    import app.services.research as svc
    from app.services.multifactor import rated
    put('annual:shared:AAPL',{'rows':{'2025':{'eps':7,'provenance':'SEC_10K'}},'updated_at':'original'})
    monkeypatch.setattr(svc,'fetch',Mock(side_effect=RuntimeError('limited')))
    r=research('AAPL');assert r['price'] is None and r['date']=='' and r['data_status']=='fundamentals_only'
    assert rated(r,'public')['annual_rows']['2025']['eps']==7
    from app.channels.commands import format_quote
    assert '年度財報' in format_quote(r)


def test_worker_reuses_secret_caps_requests_and_caches(monkeypatch):
    import jobs.refresh_us_prices as job
    monkeypatch.setenv('FINMIND_TOKEN','fake-token');monkeypatch.setenv('ANNUAL_SYMBOLS','AAPL,MSFT,VOO')
    monkeypatch.setattr(job,'local_now',lambda:__import__('datetime').datetime(2026,11,9))
    def load(url,params,**kw):
        assert kw['headers']['Authorization']=='Bearer fake-token' and 'token' not in params
        data=[{**r,'stock_id':params['data_id']} for r in records()]
        return {'status':200,'data':data}
    loader=Mock(side_effect=load);monkeypatch.setattr(job,'fetch_json',loader)
    job.run();assert loader.call_count==2
    assert get('usdaily:quote:AAPL')['price']==169
    job.run();assert loader.call_count==3
    job.run();assert loader.call_count==3


def test_worker_shared_source_cooldown(monkeypatch):
    import jobs.refresh_us_prices as job
    monkeypatch.setenv('FINMIND_TOKEN','x');monkeypatch.setenv('ANNUAL_SYMBOLS','AAPL,MSFT')
    loader=Mock(return_value={'status':429});monkeypatch.setattr(job,'fetch_json',loader)
    job.run();assert loader.call_count==1
    job.run();assert loader.call_count==1
