from datetime import date,timedelta
import time
import pytest
from app.providers.trailing import ttm_amount,us_trailing,taiwan_trailing
from app.providers.annual_free import TW_DATASETS
from app.services.trailing_metrics import attach
from app.services.annual_data import save_ttm_eps
from app.db import get
from jobs.refresh_paid_dividends import parse_apple
TODAY=date(2026,11,9)
def r(v,s,e):return {'value':v,'start':s,'end':e,'filed':'2026-11-01'}

def test_ytd_ttm_and_equity():
    records=[r(100,'2025-01-01','2025-12-31'),r(90,'2026-01-01','2026-09-30'),r(60,'2025-01-01','2025-09-30')]
    x=ttm_amount(records);assert x['value']==130 and x['start']=='2025-10-01'
    eq=[r(200,None,'2025-09-30'),r(320,None,'2026-09-30')]
    result=us_trailing({'net_income':records,'equity':eq},TODAY)
    assert result['roe_ttm_pct']['value']==50 and 'eps_ttm' not in result

def test_missing_prior_period_no_fallback():
    assert ttm_amount([r(100,'2025-01-01','2025-12-31'),r(90,'2026-01-01','2026-09-30')]) is None

def test_eps_must_match_latest_twelve_months():
    latest=r(10,'2025-10-01','2026-09-30')
    result=us_trailing({'net_income':[latest],'eps':[r(7,'2025-10-01','2026-09-30')]},TODAY)
    assert result['eps_ttm']['value']==7
    assert 'eps_ttm' not in us_trailing({'net_income':[latest],'eps':[r(7,'2024-10-01','2025-09-30')]},TODAY)

def test_tw_four_quarters_no_eps_sum():
    inc=[{'stock_id':'2330','date':d,'type':'IncomeAfterTaxes','value':20} for d in ['2025-12-31','2026-03-31','2026-06-30','2026-09-30']]
    eq=[{'stock_id':'2330','date':d,'type':'Equity','value':v} for d,v in [('2025-09-30',100),('2026-09-30',300)]]
    result=taiwan_trailing('2330.TW',{TW_DATASETS[0]:inc,TW_DATASETS[1]:eq},TODAY)
    assert result['roe_ttm_pct']['value']==40 and 'eps_ttm' not in result
    assert not taiwan_trailing('2330.TW',{TW_DATASETS[0]:inc[1:],TW_DATASETS[1]:eq},TODAY)

def quote():return {'symbol':'AAPL','kind':'STOCK','currency':'USD','price':100,'date':'2026-11-06','warnings':[]}

def test_paid_future_excluded_and_denominator_date():
    paid={'currency':'USD','fetched_at':time.time(),'source':'https://example.com','payments':[
        {'date':'2025-01-01','amount':9},{'date':'2025-11-13','amount':1},{'date':'2026-08-13','amount':2},{'date':'2026-11-16','amount':99}]}
    result=attach(quote(),{},paid,today=TODAY)
    assert result['yield']==3 and result['yield_basis']=='trailing_paid_365d'
    assert result['trailing_details']['paid_yield_pct']['price_date']=='2026-11-06'
    paid['splits']=['2026-03-01'];assert attach(quote(),{},paid,today=TODAY)['yield'] is None

def test_no_legacy_values_without_period():
    result=attach({**quote(),'eps':99,'roe':.9,'yield':10},{},today=TODAY)
    assert result['eps'] is None and result['roe'] is None and result['yield'] is None

def test_apple_payable_not_record_date():
    html='<table><tr><th>Declared</th><th>Record</th><th>Payable</th><th>Amount</th><th>Type</th></tr><tr><td>x</td><td>Nov 12, 2026</td><td>November 16, 2026</td><td>$0.27</td><td>Regular Cash</td></tr><tr><td>x</td><td>x</td><td>August 31, 2020*</td><td>N/A</td><td>4-for-1 Stock Split</td></tr></table>'
    p=parse_apple(html);assert p['payments']==[{'date':'2026-11-16','amount':.27}] and p['splits']==['2020-08-31']

def test_manual_eps_period_and_isolation():
    from app.services.freshness import local_now
    today=local_now().date()
    body={'confirmed':True,'value':3,'period_start':str(today-timedelta(days=364)),'period_end':str(today),'source':'https://example.com/report'}
    save_ttm_eps('Ualice','2330',body)
    assert get('ttm:Ualice:2330.TW')['value']==3 and get('ttm:Ubob:2330.TW') is None
    with pytest.raises(ValueError):save_ttm_eps('Ualice','2330',{**body,'period_end':'2099-01-01'})
    with pytest.raises(ValueError):save_ttm_eps('Ualice','2330',{**body,'confirmed':False})

def test_ttm_eps_api_auth_size_and_invalid_source():
    from fastapi.testclient import TestClient
    from app.api.server import app
    from app.services.freshness import local_now
    today=local_now().date()
    body={'confirmed':True,'value':2,'period_start':str(today-timedelta(days=364)),'period_end':str(today),'source':'https://example.com/report'}
    auth={'Authorization':'Bearer '+'a'*24}
    with TestClient(app) as client:
        assert client.put('/ttm-eps/AAPL',json=body).status_code==401
        assert client.put('/ttm-eps/AAPL',headers=auth,json=body).status_code==200
        assert client.put('/ttm-eps/AAPL',headers=auth,json={**body,'source':123}).status_code==400
        assert client.put('/ttm-eps/AAPL',headers=auth,content='x'*4097).status_code==413
