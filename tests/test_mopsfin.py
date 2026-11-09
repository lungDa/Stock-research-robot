import copy,time
from datetime import date
from unittest.mock import Mock
import pytest
from app.db import get,put
from app.providers.mopsfin import parse_catalog,parse_company,annual_fields,parse_annual,request
from app.services.multifactor import annual_rows,rated,rated_many

TODAY=date(2026,11,9)
DISPLAY='6488 環球晶'
CATALOG='<a class="compareClass ystClass" name="EPS" label="元">每股盈餘</a><a class="compareClass" name="ROE" label="%">權益報酬率</a>'


def payload(field='eps',display=DISPLAY):
    return {'ylabel':'元' if field=='eps' else '%','xaxisList':['2023Q4','2024Q4','2025Q4'],
        'graphData':[{'label':display,'data':[[0,3],[1,-2],[2,4.5]]}],
        'displayCompanyId':[display],'checkedNameList':[display],'extraNameList':[]}


def test_catalog_units_and_exact_company_identity():
    assert parse_catalog(CATALOG)['eps']['code']=='EPS'
    assert parse_company({'suggestions':['6488 環球晶','64880 其他']},'6488.TWO')==DISPLAY
    for body in ({'suggestions':['64880 其他']},{'suggestions':['6488 環球晶','6488 不同名稱']},{}):
        with pytest.raises(ValueError):parse_company(body,'6488.TWO')
    with pytest.raises(ValueError):parse_catalog(CATALOG.replace('label="元"','label="千元"'))


def test_catalog_discovers_metric_codes_from_official_labels():
    catalog=parse_catalog(CATALOG.replace('name="EPS"','name="EarningsPerShare"').replace('name="ROE"','name="ReturnOnEquity"'))
    assert annual_fields('eps',DISPLAY,catalog['eps'])['compareItem']=='EarningsPerShare'
    assert annual_fields('roe_pct',DISPLAY,catalog['roe_pct'])['compareItem']=='ReturnOnEquity'
    result=parse_annual(payload(),'6488.TWO','eps',DISPLAY,TODAY,catalog['eps'])
    assert result['2025']['field_sources']['eps']['request']['compareItem']=='EarningsPerShare'


@pytest.mark.parametrize('symbol',['6488.TWO','2330.TW'])
def test_annual_eps_and_roe_accept_both_markets(symbol):
    display=symbol.split('.')[0]+' 測試公司'
    for field in ('eps','roe_pct'):
        result=parse_annual(payload(field,display),symbol,field,display,TODAY)
        assert result['2025'][field]==4.5 and result['2024'][field]==-2
        source=result['2025']['field_sources'][field]
        assert source['period_start']=='2025-01-01' and source['period_end']=='2025-12-31'
        assert source['request']['quarter']=='false' and source['request']['qnumber']=='4'


@pytest.mark.parametrize('change',[
    {'ylabel':'千元'},{'xaxisList':['2023Q1','2024Q1','2025Q1']},
    {'xaxisList':['2023Q4','2024Q4','2024Q4']},{'quarter':True},{'qnumber':3},
    {'displayCompanyId':['2330 台積電']},{'checkedNameList':['6488 其他公司']},
    {'extraNameList':['產業平均']},{'graphData':[{'label':'產業平均','data':[[0,99]]}]},
    {'graphData':[{'label':DISPLAY,'data':[[0,3]]},{'label':'產業平均','data':[[0,99]]}]},
    {'graphData':[{'label':DISPLAY,'data':[[0,3],[0,4]]}]},
    {'graphData':[{'label':DISPLAY,'data':[[1.5,3]]}]},
    {'graphData':[{'label':DISPLAY,'data':[[0,float('nan')]]}]},
    {'graphData':[{'label':DISPLAY,'data':[[0,'10,00']]}]},
])
def test_rejects_ambiguous_identity_basis_period_or_number(change):
    with pytest.raises(ValueError):parse_annual({**payload(),**change},'6488.TWO','eps',DISPLAY,TODAY)


def test_null_stays_missing_zero_is_real_and_current_year_not_full_year():
    data=payload();data['xaxisList']=['2024Q4','2025Q4','2026Q4']
    data['graphData'][0]['data']=[[0,None],[1,0],[2,99]]
    result=parse_annual(data,'6488.TWO','eps',DISPLAY,TODAY)
    assert list(result)==['2025'] and result['2025']['eps']==0


def seed_metadata():
    put('mopsfin:catalog',{'at':time.time(),'metrics':parse_catalog(CATALOG)})
    put('mopsfin:company:6488.TWO',{'at':time.time(),'display':DISPLAY})


def test_worker_runs_without_finmind_and_preserves_private_values(monkeypatch):
    import jobs.refresh_tw_financials as job
    monkeypatch.delenv('FINMIND_TOKEN',raising=False);seed_metadata()
    put('annual:Ualice:6488.TWO',{'2025':{'eps':8,'provenance':'user_import'}})
    loader=Mock(side_effect=lambda path,**kw:payload('eps' if kw['form']['compareItem']=='EPS' else 'roe_pct'))
    monkeypatch.setattr(job,'request',loader)
    result=job.run(['6488.TWO'],max_requests=2)
    assert result['official_requests']==2 and result['updated_symbols']==1
    assert annual_rows('Ubob','6488.TWO')['2025']['eps']==4.5
    assert annual_rows('Ubob','6488.TWO')['2025']['roe_pct']==4.5
    assert annual_rows('Ualice','6488.TWO')['2025']['eps']==8
    assert len(annual_rows('Ubob','6488.TWO')['2025']['field_sources'])==2
    job.run(['6488.TWO']);assert loader.call_count==2


def test_cold_metadata_budget_resumes_same_metric_next_batch(monkeypatch):
    import jobs.refresh_tw_financials as job
    calls=[]
    def load(path,**kwargs):
        calls.append(path)
        if path=='/':return CATALOG
        if path=='/suggestCompany':return {'suggestions':[DISPLAY]}
        return payload('eps' if kwargs['form']['compareItem']=='EPS' else 'roe_pct')
    monkeypatch.setattr(job,'request',load)
    first=job.run(['6488.TWO'],max_requests=2)
    assert first['official_requests']==2 and get('financial:official:6488.TWO') is None
    job.run(['6488.TWO'],max_requests=2)
    assert calls==['/','/suggestCompany','/compare/data','/compare/data']
    assert get('financial:official:6488.TWO')['rows']['2025']['eps']==4.5


def test_worker_failure_preserves_cache_and_stops_for_source_cooldown(monkeypatch):
    import jobs.refresh_tw_financials as job
    import requests
    seed_metadata();put('financial:official:6488.TWO',{'rows':{'2025':{'eps':7}}})
    response=Mock(status_code=429);error=requests.HTTPError(response=response)
    loader=Mock(side_effect=error);monkeypatch.setattr(job,'request',loader)
    job.run(['6488.TWO']);job.run(['6488.TWO'])
    assert loader.call_count==1 and get('financial:official:6488.TWO')['rows']['2025']['eps']==7
    assert get('annual:source:mopsfin')['next_attempt']>time.time()


def test_new_background_source_shares_two_request_budget(monkeypatch):
    import jobs.refresh_tw_financials as official
    import jobs.refresh_eps as eps
    import jobs.refresh_annual as annual
    from app.services.query_fundamentals import process_download,status
    monkeypatch.setattr(official,'run',Mock(return_value={'official_requests':2,'updated_symbols':1,'failed_feeds':0}))
    old=Mock();monkeypatch.setattr(eps,'run',old);monkeypatch.setattr(annual,'run',old)
    process_download('6488.TWO')
    old.assert_not_called();assert status('6488.TWO')['official_requests']==2


def test_bounded_http_uses_fixed_host_and_never_follows_redirect(monkeypatch):
    response=Mock(status_code=200);response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
    response.iter_content.return_value=[b'{"suggestions":["6488 Company"]}']
    loader=Mock(return_value=response);monkeypatch.setattr('app.providers.mopsfin.requests.request',loader)
    assert request('/suggestCompany',params={'query':'6488'})['suggestions']
    args=loader.call_args
    assert args.args[1]=='https://mopsfin.twse.com.tw/suggestCompany'
    assert args.kwargs['timeout']==(2,2) and not args.kwargs['allow_redirects']
    with pytest.raises(ValueError):request('https://other.example/steal')


def test_response_byte_cap_rejects_oversize_instead_of_partial_json(monkeypatch):
    response=Mock(status_code=200);response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
    response.iter_content.return_value=[b'x'*(1048576+1)]
    monkeypatch.setattr('app.providers.mopsfin.requests.request',Mock(return_value=response))
    with pytest.raises(ValueError):request('/suggestCompany',params={'query':'6488'})


def test_rated_batch_reads_official_fields_identically():
    from tests.test_improvements import quote
    seed_metadata()
    rows=parse_annual(payload(),'6488.TWO','eps',DISPLAY,TODAY)
    roe=parse_annual(payload('roe_pct'),'6488.TWO','roe_pct',DISPLAY,TODAY)
    for year,r in roe.items():
        rows[year]['roe_pct']=r['roe_pct'];rows[year]['field_sources'].update(r['field_sources'])
    put('financial:official:6488.TWO',{'rows':rows})
    data=quote('6488.TWO')
    assert rated(data,'public')==rated_many([data],'public')[0]
    assert rated(data,'public')['annual_rows']['2025']['eps']==4.5


def test_official_annual_data_visible_even_when_market_is_unavailable(monkeypatch):
    import app.services.research as research
    put('financial:official:6488.TWO',{'rows':parse_annual(payload(),'6488.TWO','eps',DISPLAY,TODAY)})
    monkeypatch.setattr(research,'fetch',Mock(side_effect=TimeoutError()))
    data=rated(research.research('6488.TWO'),'public')
    assert data['price'] is None and data['kind']=='STOCK'
    assert data['annual_rows']['2025']['eps']==4.5 and data['rating']['grade']=='資料不足'


def test_manual_contract_probe_four_calls_and_no_ttm_claim():
    from scripts.check_tw_financial_contract import probe
    calls=[]
    def download(path,**kwargs):
        calls.append(path)
        if path=='/':return CATALOG
        if path=='/suggestCompany':return {'suggestions':[DISPLAY]}
        return payload('eps' if kwargs['form']['compareItem']=='EPS' else 'roe_pct')
    result=probe('6488.TWO',download)
    assert len(calls)==4 and result['requests']==4 and not result['ttm_eps_verified']
    assert result['sample']['2025']['eps']==4.5 and result['sample']['2025']['roe_pct']==4.5


def test_independent_refresh_marks_returned_source_failure_as_partial(monkeypatch):
    import jobs.refresh_data as job
    import jobs.refresh_tw_financials as official
    from jobs import maintenance,refresh_fundamentals,refresh_eps,refresh_annual,refresh_us_prices,refresh_paid_dividends
    for module in (maintenance,refresh_fundamentals,refresh_eps,refresh_annual,refresh_us_prices,refresh_paid_dividends):
        monkeypatch.setattr(module,'run',Mock(return_value={'state':'cached'}))
    monkeypatch.setattr(official,'run',Mock(return_value={'state':'failed','failed_feeds':1}))
    result=job.run()
    assert result['state']=='partial' and result['steps']['tw_financials']['state']=='partial'
