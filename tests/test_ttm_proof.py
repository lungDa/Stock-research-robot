import copy
from datetime import date,timedelta
import pytest
from fastapi.testclient import TestClient
from app.db import get,put
from app.services.ttm_proof import calculate,is_calendar_ttm
from app.services.annual_data import save_ttm_components
from app.providers.trailing import reported_twelve_month_eps,taiwan_trailing
from app.providers.annual_free import TW_DATASETS
from app.api.server import app

TODAY=date(2026,11,9)


def body():
    dates=[('2025-10-01','2025-12-31'),('2026-01-01','2026-03-31'),('2026-04-01','2026-06-30'),('2026-07-01','2026-09-30')]
    return {'currency':'TWD','money_unit':'TWD_THOUSAND','share_unit':'THOUSAND_SHARES',
        'confirmed':True,'ordinary_profit_confirmed':True,'share_basis_confirmed':True,
        'share_basis_date':'2026-11-01','share_basis_source':'https://example.com/restatement',
        'quarters':[{'period_start':a,'period_end':b,'ordinary_profit':100+i*100,
            'weighted_average_shares':100,'reported_basic_eps':1+i,'source':'https://example.com/report'} for i,(a,b) in enumerate(dates)]}


def test_profit_and_share_evidence_not_sum_of_eps():
    data=body();result=calculate(data,TODAY)
    assert result['value']==10
    assert result['calculation']['ordinary_profit_TWD']==1000000
    assert result['calculation']['weighted_average_shares']==100000
    assert not result['calculation']['source_content_independently_verified']
    data['quarters'][0].update(weighted_average_shares=50,reported_basic_eps=2)
    result=calculate(data,TODAY)
    expected=1000000/((50000*92+100000*273)/365)
    assert result['value']==pytest.approx(expected)
    assert result['value']!=sum(q['reported_basic_eps'] for q in data['quarters'])


@pytest.mark.parametrize('change',[
    {'confirmed':False},{'ordinary_profit_confirmed':False},{'share_basis_confirmed':False},
    {'money_unit':'USD'},{'share_unit':'TWD'},{'currency':'USD'},
    {'share_basis_date':'2025-01-01'},{'share_basis_date':'2099-01-01'},
    {'share_basis_source':'http://example.com/report'},
])
def test_rejects_unverified_basis_or_wrong_units(change):
    with pytest.raises(ValueError):calculate({**body(),**change},TODAY)


@pytest.mark.parametrize('field,value',[
    ('ordinary_profit',None),('ordinary_profit',float('nan')),('weighted_average_shares',0),
    ('weighted_average_shares',-1),('weighted_average_shares',True),('reported_basic_eps',99),
    ('period_start','2025-01-01'),('period_end','2025-11-30'),('source','http://example.com/report'),
])
def test_invalid_single_quarter_cannot_be_saved(field,value):
    data=body();data['quarters'][0][field]=value
    with pytest.raises(ValueError):calculate(data,TODAY)


def test_duplicate_missing_quarter_and_cumulative_intervals_rejected():
    data=body();data['quarters'][1]=copy.deepcopy(data['quarters'][0])
    with pytest.raises(ValueError):calculate(data,TODAY)
    with pytest.raises(ValueError):calculate({**body(),'quarters':body()['quarters'][:3]},TODAY)
    data=body();data['quarters'][2]['period_start']='2026-01-01'
    with pytest.raises(ValueError):calculate(data,TODAY)


def test_loss_is_valid_and_order_can_be_reversed():
    data=body();data['quarters'][0].update(ordinary_profit=-100,reported_basic_eps=-1)
    assert calculate(data,TODAY)['value']==8
    data['quarters'].reverse();assert calculate(data,TODAY)['value']==8


def test_calendar_ttm_exact_and_leap_year():
    assert is_calendar_ttm(date(2023,4,1),date(2024,3,31))
    assert not is_calendar_ttm(date(2023,4,2),date(2024,3,31))
    assert not is_calendar_ttm(date(2025,11,10),date(2026,11,9))


def test_personal_proof_is_atomic_and_isolated():
    result=save_ttm_components('Ualice','6488.TWO',body())
    assert result['value']==10 and get('ttm:Ubob:6488.TWO') is None
    bad=body();bad['quarters'][3]['weighted_average_shares']=0
    with pytest.raises(ValueError):save_ttm_components('Ualice','6488.TWO',bad)
    assert get('ttm:Ualice:6488.TWO')['value']==10
    with pytest.raises(ValueError):save_ttm_components('Ualice','AAPL',body())


def test_proof_api_auth_and_size():
    auth={'Authorization':'Bearer '+'a'*24}
    with TestClient(app) as client:
        assert client.put('/ttm-eps-components/6488.TWO',json=body()).status_code==401
        assert client.put('/ttm-eps-components/6488.TWO',headers=auth,json=body()).status_code==200
        assert client.put('/ttm-eps-components/6488.TWO',headers=auth,content='x'*16385).status_code==413


def test_reported_annual_eps_only_for_exact_current_twelve_month_window():
    rows={'2025':{'eps':5,'field_sources':{'eps':{'provenance':'MOPSFIN_annual','url':'https://mopsfin.twse.com.tw/'}}}}
    result=reported_twelve_month_eps(rows,{},'2025Q4',date(2026,3,31))
    assert result['value']==5 and result['period_start']=='2025-01-01' and result['period_end']=='2025-12-31'
    assert not reported_twelve_month_eps(rows,{},'2026Q1',date(2026,5,1))
    assert not reported_twelve_month_eps(rows,{},'2025Q4',TODAY)
    assert not reported_twelve_month_eps(rows,{'roe':{'period_end':'2026-03-31'}},'2025Q4',date(2026,5,1))


def test_roe_keeps_auditable_income_and_equity_inputs():
    inc=[{'stock_id':'6488','date':d,'type':'IncomeAfterTaxes','value':20} for d in ['2025-12-31','2026-03-31','2026-06-30','2026-09-30']]
    eq=[{'stock_id':'6488','date':d,'type':'Equity','value':v} for d,v in [('2025-09-30',100),('2026-09-30',300)]]
    result=taiwan_trailing('6488.TWO',{TW_DATASETS[0]:inc,TW_DATASETS[1]:eq},TODAY)['roe_ttm_pct']
    proof=result['calculation']
    assert result['value']==40 and proof['income_total']==80 and proof['mean_equity']==200
    assert proof['scope']=='total_consolidated_income_and_equity'


def test_huge_intermediate_values_do_not_pass_as_zero_eps():
    data=body();data['money_unit']='TWD';data['share_unit']='SHARES'
    for row in data['quarters']:row.update(ordinary_profit=1e308,weighted_average_shares=1e307,reported_basic_eps=None)
    with pytest.raises(ValueError):calculate(data,TODAY)


def test_etf_not_accepted_as_company_proof():
    put('quote:0050.TW',{'kind':'ETF'})
    with pytest.raises(ValueError):save_ttm_components('Ualice','0050',body())
