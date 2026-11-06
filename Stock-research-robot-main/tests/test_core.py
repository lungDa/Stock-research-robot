import pandas as pd
import pytest
from app.providers.market import normalize,dividend_yield
from app.services.analysis import evaluate
from app.services.watchlist import add,watches,remove
from app.db import claim

def test_normalize():
    assert normalize('2330')=='2330.TW'
    assert normalize('6488.two')=='6488.TWO'
    assert normalize('brk-b')=='BRK-B'
    with pytest.raises(ValueError): normalize('../secret')

def test_old_dividends_not_counted():
    div=pd.Series([5.,2.],index=pd.to_datetime(['2020-01-01','2025-12-01'],utc=True))
    assert dividend_yield(div,100,'2026-11-06')==2

def test_future_dividends_excluded():
    div=pd.Series([3.],index=pd.to_datetime(['2027-01-01'],utc=True))
    assert dividend_yield(div,100,'2026-11-06')==0

def test_missing_values_not_zero_or_match():
    d={'kind':'STOCK','eps':None,'roe':None,'yield':None,'pe':None}
    r=evaluate(d,'income')
    assert not r['matched'] and all(v is None for v in r['checks'].values())

def test_etf_uses_separate_rules():
    r=evaluate({'kind':'ETF','yield':4,'volatility':15,'expense_ratio':.001},'income')
    assert r['matched'] and 'EPS為正' not in r['checks']

def test_watchlist_isolation_and_idempotency():
    add('Ualice','AAPL');add('Ualice','AAPL');add('Ubob','MSFT')
    remove('Ubob','AAPL')
    assert watches('Ualice')==['AAPL'] and watches('Ubob')==['MSFT']

def test_claim_atomic():
    assert claim('same',{})
    assert not claim('same',{})
