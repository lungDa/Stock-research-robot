import copy
from datetime import date
import pytest
from fastapi.testclient import TestClient
from app.db import put,get
from app.api.server import app
from app.services.annual_data import supplement,supplemental_rows
from app.services.multifactor import annual_rows
from app.providers.annual_free import TW_DATASETS,taiwan_rows,paid_dividend_total
from jobs.refresh_annual import compact


def body(**change):
    data={'confirmed':True,'unit':'TWD_THOUSAND','rows':[{'year':2025,'eps':66.25,'cash_dividends_paid':1234,'source_url':'https://example.com/annual2025.pdf'}]}
    data.update(change);return data


def test_supplement_converts_units_and_preserves_existing_private_shared():
    put('annual:Ualice:2330.TW',{'2025':{'roe_pct':20},'2024':{'eps':40}})
    put('annual:shared:2330.TW',{'rows':{'2025':{'revenue':100,'cash_dividends_paid':99}}})
    result=supplement('Ualice','2330',body())
    r=annual_rows('Ualice','2330.TW')['2025']
    assert r['eps']==66.25 and r['cash_dividends_paid']==1234000 and r['roe_pct']==20 and r['revenue']==100
    assert get('annual:Ualice:2330.TW')['2024']['eps']==40
    assert annual_rows('Ubob','2330.TW')['2025']['cash_dividends_paid']==99
    assert result['updated_fields']==2 and r['field_sources']['eps']['unit']=='TWD_PER_SHARE'


def test_blanks_not_deleted_negative_eps_and_zero_dividend_valid():
    supplement('Ualice','2330',body())
    supplement('Ualice','2330',body(rows=[{'year':2025,'eps':-2,'source_url':'https://example.com/correction'}]))
    assert get('annual:Ualice:2330.TW')['2025']['cash_dividends_paid']==1234000
    supplement('Ualice','2330',body(unit='TWD',rows=[{'year':2024,'cash_dividends_paid':0,'source_url':'https://example.com/report'}]))
    assert get('annual:Ualice:2330.TW')['2024']['cash_dividends_paid']==0


@pytest.mark.parametrize('change',[{'confirmed':False},{'unit':'USD'},
    {'rows':[{'year':2025,'eps':True,'source_url':'https://example.com'}]},
    {'rows':[{'year':2025,'eps':float('nan'),'source_url':'https://example.com'}]},
    {'rows':[{'year':2025,'cash_dividends_paid':-1,'source_url':'https://example.com'}]},
    {'rows':[{'year':2025,'eps':1,'source_url':'http://example.com'}]},
    {'rows':[{'year':2025,'source_url':'https://example.com'}]},
    {'rows':[{'year':2099,'eps':1,'source_url':'https://example.com'}]}])
def test_invalid_rows_atomic(change):
    put('annual:Ualice:2330.TW',{'2024':{'eps':3}})
    with pytest.raises(ValueError):supplement('Ualice','2330',body(**change))
    assert get('annual:Ualice:2330.TW')=={'2024':{'eps':3}}


def test_api_auth_scope_and_limits():
    a={'Authorization':'Bearer '+'a'*24};b={'Authorization':'Bearer '+'b'*24}
    with TestClient(app) as c:
        assert c.patch('/annual-supplement/2330',json=body()).status_code==401
        assert c.patch('/annual-supplement/2330',headers=a,json=body()).status_code==200
        assert c.get('/annual-supplement/2330',headers=a).json()['rows'][0]['eps']==66.25
        assert c.get('/annual-supplement/2330',headers=b).json()['rows']==[]
        assert c.patch('/annual-supplement/AAPL',headers=a,json=body()).status_code==400
        assert c.patch('/annual-supplement/2330',headers=a,content='x'*32769).status_code==413


def cash(label,value=-500):
    return {'date':'2025-12-31','stock_id':'2330','type':'SomeProviderTag','origin_name':label,'value':value}


def test_compaction_preserves_unfamiliar_labels_and_total_is_not_doubled():
    records=compact(TW_DATASETS[2],[cash('發放股利'),cash('發放股利'),cash('支付利息',-99)],'2330')
    r=taiwan_rows('2330.TW',{TW_DATASETS[2]:records},date(2026,11,9))['2025']
    assert r['cash_dividends_paid']==500 and len(records)==2


def test_conflicting_cashflow_totals_and_unsafe_labels_not_accepted():
    assert paid_dividend_total([cash('發放股利'),cash('支付股利',-501)],'2330','2025-12-31') is None
    assert paid_dividend_total([cash('支付利息及股利'),cash('應付股利'),cash('支付予非控制權益之股利')],'2330','2025-12-31') is None
    assert paid_dividend_total([cash('支付股利',0)],'2330','2025-12-31')==0


def test_cash_schema_refetch_once_respects_new_cooldown(monkeypatch):
    import time
    import jobs.refresh_annual as job
    from unittest.mock import Mock
    monkeypatch.setenv('FINMIND_TOKEN','fake');monkeypatch.setenv('ANNUAL_SYMBOLS','2330.TW')
    monkeypatch.delenv('SEC_USER_AGENT',raising=False)
    for dataset in TW_DATASETS:
        put('annual:feed:2330.TW:'+dataset,{'next_attempt':time.time()+86400,'schema':2,'records':[]})
    put('annual:feed:2330.TW:'+TW_DATASETS[2],{'next_attempt':time.time()+86400,'schema':1,'records':[]})
    loader=Mock(return_value={'status':200,'data':[cash('發放股利')]})
    monkeypatch.setattr(job,'fetch_json',loader)
    job.run();assert loader.call_count==1
    assert get('annual:shared:2330.TW')['rows']['2025']['cash_dividends_paid']==500
    job.run();assert loader.call_count==1
