import copy,csv,io,time
from datetime import date
import pytest
from app.db import get,put
from app.services.multifactor import DEFAULT,validate,evaluate,annual_rows,save_settings,settings_for,rated_many
from app.services.annual_data import FIELDS,import_csv
TODAY=date(2026,11,6)
def annual():
    return {str(y):dict(eps=3,roe_pct=20,cash_yield_pct=6,cash_dividend_per_share=2,
        operating_cash_flow=200,capital_expenditure=50,cash_dividends_paid=100,revenue=100*1.1**(y-2015)) for y in range(2015,2026)}
def quote(symbol='2330.TW'):
    return dict(symbol=symbol,name='測試公司',kind='STOCK',price=110,adjusted_close=110,ma20=100,ma60=90,
        date=TODAY.isoformat(),currency='TWD',cached_at=time.time(),data_status='partial')
def test_complete_strong_and_required_failure_watch():
    rows=annual();assert evaluate(quote(),DEFAULT,rows,TODAY)['grade']=='強力買'
    rows['2025']['eps']=1
    r=evaluate(quote(),DEFAULT,rows,TODAY)
    assert r['grade']=='觀望' and r['checks'][0]['passed'] is False

def test_five_year_eps_average_not_every_year():
    rows=annual();rows['2023']['eps']=0
    assert evaluate(quote(),DEFAULT,rows,TODAY)['checks'][1]['passed'] is True

def test_each_year_cash_flow_and_coverage():
    rows=annual();rows['2022']['capital_expenditure']=210
    r=evaluate(quote(),DEFAULT,rows,TODAY)
    assert r['checks'][5]['passed'] is False and r['checks'][6]['passed'] is False
    rows=annual();rows['2022']['cash_dividends_paid']=200
    assert evaluate(quote(),DEFAULT,rows,TODAY)['checks'][6]['passed'] is False

def test_cagr_five_year_needs_six_rows():
    rows=annual();r=evaluate(quote(),DEFAULT,rows,TODAY)
    assert r['checks'][7]['value']==pytest.approx(10)
    del rows['2020']
    assert evaluate(quote(),DEFAULT,rows,TODAY)['checks'][7]['value'] is None

def test_dividends_ten_years_no_gap():
    rows=annual();rows['2020']['cash_dividend_per_share']=0
    assert evaluate(quote(),DEFAULT,rows,TODAY)['checks'][3]['passed'] is False
    rows=annual();del rows['2016']
    assert evaluate(quote(),DEFAULT,rows,TODAY)['grade']=='資料不足'

def test_missing_block_and_available_capped_buy():
    q=quote();q['ma60']=None
    assert evaluate(q,DEFAULT,annual(),TODAY)['grade']=='資料不足'
    c=copy.deepcopy(DEFAULT);c['missing_policy']='available'
    assert evaluate(q,c,annual(),TODAY)['grade']=='買'

def test_quarter_eps_cannot_replace_annual():
    q=quote();q.update(eps=99,roe=.99,**{'yield':99})
    assert evaluate(q,DEFAULT,{},TODAY)['grade']=='資料不足'

def test_etf_uses_separate_rules_and_period_basis():
    q=quote();q.update(kind='ETF',expense_ratio=.001,expense_ratio_basis='annual_total_expense',
       volatility=10,yield_basis='trailing_paid_365d',**{'yield':5})
    assert evaluate(q,DEFAULT,{},TODAY)['grade']=='強力買'
    del q['yield_basis']
    assert evaluate(q,DEFAULT,{},TODAY)['grade']=='資料不足'

def test_settings_invalid_and_user_isolation():
    c=copy.deepcopy(DEFAULT);c['stock_rules'][0]['threshold']=4;save_settings('Ualice',c)
    assert settings_for('Ubob')['stock_rules'][0]['threshold']==1
    for change in [('daily_cap',11),('strong_score',60)]:
        c=copy.deepcopy(DEFAULT);c[change[0]]=change[1]
        with pytest.raises(ValueError):validate(c)
    c=copy.deepcopy(DEFAULT);c['stock_rules'][0]['weight']=float('nan')
    with pytest.raises(ValueError):validate(c)

def csv_text(rows):
    out=io.StringIO();w=csv.DictWriter(out,fieldnames=FIELDS);w.writeheader()
    for row in rows:w.writerow(row)
    return out.getvalue()

def test_annual_import_atomic_validation_and_isolation():
    valid=dict(year=2025,eps=3,source_url='https://example.com/report')
    import_csv('Ualice','2330',csv_text([valid]))
    assert annual_rows('Ualice','2330.TW')['2025']['eps']==3
    assert not annual_rows('Ubob','2330.TW')
    with pytest.raises(ValueError):import_csv('Ualice','2330',csv_text([valid,valid]))
    assert annual_rows('Ualice','2330.TW')['2025']['eps']==3
    with pytest.raises(ValueError):import_csv('Ualice','2330',csv_text([{**valid,'capital_expenditure':-3}]))
    with pytest.raises(ValueError):import_csv('Ualice','2330',csv_text([{**valid,'eps':'NaN'}]))

def test_batch_uses_personal_data_and_stale_momentum_blocked():
    put('annual:Ualice:2330.TW',annual())
    assert rated_many([quote()],'Ualice')[0]['rating']['grade']=='強力買'
    assert rated_many([quote()],'Ubob')[0]['rating']['grade']=='資料不足'
    q=quote();q['data_status']='stale'
    assert evaluate(q,DEFAULT,annual(),TODAY)['grade']=='資料不足'
