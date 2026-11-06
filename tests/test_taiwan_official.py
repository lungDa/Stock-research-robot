from datetime import date
from unittest.mock import Mock
import pandas as pd
import pytest
from app.providers import taiwan_official as official
from app.providers import market
from app.services.analysis import enrich
from app.db import get, put

@pytest.mark.parametrize('raw',['115/11/05','1151105','20261105','2026-11-05'])
def test_dates(raw): assert official.trading_date(raw)=='2026-11-05'

def test_twse_month_price_commas_and_no_trade():
    rows=official.parse_month({'fields':['日期','成交股數','收盤價'],'data':[['115/10/01','20,666,092','2,510.00'],['115/10/02','0','--']]},'TW')
    assert rows==[{'date':'2026-10-01','close':2510.,'volume':20666092.}]

def test_tpex_month_thousands_of_shares():
    rows=official.parse_month({'tables':[{'fields':['日 期','成交仟股','收盤'],'data':[['115/10/01','24,330','1,085.00']]}]},'TWO')
    assert rows[0]['volume']==24330000 and rows[0]['close']==1085

def test_unknown_schema_not_silent_empty():
    with pytest.raises(ValueError): official.parse_month({'fields':['wrong'],'data':[['x']]},'TW')

def test_shared_snapshot_once(monkeypatch):
    loader=Mock(return_value=[{'Date':'1151105','Code':'2330','Name':'台積電','ClosingPrice':'2,000'},{'Date':'1151105','Code':'2412','Name':'中華電','ClosingPrice':'130'}])
    monkeypatch.setattr(official,'_request',loader)
    assert official.snapshot('TW')['2330']['close']==2000
    assert official.snapshot('TW')['2412']['close']==130
    assert loader.call_count==1

def test_tpex_snapshot_schema(monkeypatch):
    monkeypatch.setattr(official,'_request',lambda *a:[{'Date':'1151105','SecuritiesCompanyCode':'6488','CompanyName':'環球晶','Close':'500'}])
    assert official.snapshot('TWO')['6488']['name']=='環球晶'

def test_failure_cached_without_repeated_network(monkeypatch):
    loader=Mock(side_effect=RuntimeError('blocked'))
    for _ in range(2):
        with pytest.raises(RuntimeError): official.cached('test-failure',10,loader)
    assert loader.call_count==1

def test_official_routing_never_calls_yahoo(monkeypatch):
    yahoo=Mock(side_effect=AssertionError('must not use Yahoo'))
    monkeypatch.setattr(market.yf,'Ticker',yahoo)
    monkeypatch.setattr(official,'fetch',lambda symbol:{'symbol':symbol})
    assert market.fetch('2330')=={'symbol':'2330.TW'}
    assert market.fetch('00679B.TWO')=={'symbol':'00679B.TWO'}
    assert yahoo.call_count==0

def test_snapshot_survives_month_failure(monkeypatch):
    monkeypatch.setattr(official,'snapshot',lambda m:{'2412':{'date':'2026-11-05','close':130,'name':'中華電'}})
    monkeypatch.setattr(official,'catalog',lambda m:{'2412':{'kind':'STOCK','name':'中華電'}})
    monkeypatch.setattr(official,'month',Mock(side_effect=RuntimeError('history offline')))
    d=enrich(official.fetch('2412.TW'))
    assert d['price']==130 and d['ma20'] is None and not d['swing']['matched']
    assert d['eps'] is None and d['data_status']=='partial' and d['source']=='臺灣證券交易所 TWSE'

def test_raw_split_disables_signal():
    rows=[{'date':x.date().isoformat(),'close':100 if i<65 else 25,'volume':1000} for i,x in enumerate(pd.date_range('2026-08-01',periods=70))]
    d=enrich(official.build_result('0050.TW',rows,{'kind':'ETF'},[]))
    assert d['ma20'] is None and d['volatility'] is None and not d['swing']['matched']

def test_sufficient_history_computes_moving_averages():
    rows=[{'date':x.date().isoformat(),'close':100+i,'volume':1000} for i,x in enumerate(pd.date_range('2026-08-01',periods=70))]
    d=enrich(official.build_result('2330.TW',rows,{'kind':'STOCK'},[]))
    assert d['ma20']==159.5 and d['ma60']==139.5 and d['swing']['matched']
    assert not d['income']['matched'] and d['yield'] is None

def test_scan_profile_never_backfills(monkeypatch):
    monkeypatch.setattr(official,'snapshot',lambda m:{'2412':{'date':'2026-11-05','close':130,'name':'中華電'}})
    monkeypatch.setattr(official,'catalog',lambda m:{})
    network=Mock(side_effect=AssertionError('scan must not download months'));monkeypatch.setattr(official,'month',network)
    token=official.history_months.set(0)
    try: d=official.fetch('2412.TW')
    finally: official.history_months.reset(token)
    assert d['price']==130 and network.call_count==0

def test_legacy_yahoo_cache_not_used_for_taiwan(monkeypatch):
    from app.services import research
    import time
    put('quote:2330.TW',{'cached_at':time.time(),'price':1,'source':'Yahoo Finance / yfinance'})
    fail=Mock(side_effect=RuntimeError('official unavailable'));monkeypatch.setattr(research,'fetch',fail)
    with pytest.raises(RuntimeError): research.research('2330')
    assert fail.call_count==1

def test_wrong_month_rejected(monkeypatch):
    monkeypatch.setattr(official,'_request',lambda *a,**k:{'fields':['日期','成交股數','收盤價'],'data':[['115/09/01','1','100']]})
    with pytest.raises(ValueError): official.month('2330','TW',date(2026,10,1),date(2026,11,6))
