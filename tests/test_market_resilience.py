import time
from unittest.mock import Mock
import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError
from app.providers import market
from app.services.analysis import enrich

@pytest.fixture
def ticker(monkeypatch):
    monkeypatch.setattr(market,'_cooldowns',{'history':0.,'info':0.})
    class Ticker:
        def __init__(self): self.history_calls=0;self.info_calls=0
        def history(self,**kwargs):
            self.history_calls+=1
            return pd.DataFrame({'Close':[100.+i for i in range(70)],'Adj Close':[100.+i for i in range(70)],'Volume':[1000.]*70,'Dividends':[0.]*70},index=pd.date_range('2026-01-01',periods=70,tz='UTC'))
        @property
        def info(self):
            self.info_calls+=1
            raise YFRateLimitError()
    t=Ticker();monkeypatch.setattr(market.yf,'Ticker',lambda symbol:t)
    return t

def test_info_rate_limit_keeps_history_and_does_not_retry_it(ticker):
    d=enrich(market.fetch('2330'))
    assert ticker.history_calls==1 and ticker.info_calls==1
    assert d['price']==169 and len(d['history'])==70
    assert d['data_status']=='partial' and d['warnings']
    assert d['eps'] is None and not d['income']['matched']

def test_info_cooldown_shared_across_symbols(ticker):
    market.fetch('2330');market.fetch('AAPL')
    assert ticker.history_calls==2 and ticker.info_calls==1

def test_history_limit_stops_immediate_retries(ticker,monkeypatch):
    fail=Mock(side_effect=YFRateLimitError());monkeypatch.setattr(ticker,'history',fail)
    with pytest.raises(RuntimeError):market.fetch('2330')
    with pytest.raises(RuntimeError):market.fetch('AAPL')
    assert fail.call_count==1

def test_stale_fallback_does_not_change_cache_timestamp(monkeypatch):
    from app.services import research as svc
    from app.db import put,get
    cached={'symbol':'AAPL','cached_at':time.time()-4000,'date':'2026-11-05','updated_at':'original'}
    put('quote:AAPL',cached)
    monkeypatch.setattr(svc,'fetch',Mock(side_effect=RuntimeError('limited')))
    result=svc.research('AAPL')
    assert result['data_status']=='stale'
    assert result['cached_at']==cached['cached_at'] and result['updated_at']=='original'
    assert get('quote:AAPL')==cached

def test_over_72_hours_not_used(monkeypatch):
    from app.services import research as svc
    from app.db import put
    put('quote:AAPL',{'cached_at':time.time()-73*3600})
    monkeypatch.setattr(svc,'fetch',Mock(side_effect=RuntimeError('limited')))
    with pytest.raises(RuntimeError):svc.research('AAPL')

def test_partial_cache_retried_after_five_minutes(monkeypatch):
    from app.services import research as svc
    from app.db import put
    put('quote:AAPL',{'cached_at':time.time()-301,'data_status':'partial'})
    fail=Mock(side_effect=RuntimeError('limited'));monkeypatch.setattr(svc,'fetch',fail)
    assert svc.research('AAPL')['data_status']=='stale'
    assert fail.call_count==1
