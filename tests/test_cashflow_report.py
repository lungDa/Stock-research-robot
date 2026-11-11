from datetime import date
import copy,time
from unittest.mock import Mock
import pytest,requests
from app.db import get,put
from app.providers.cashflow_report import catalog,fields,parse,ReportHTML,grid,number
from app.providers.annual_free import paid_dividend_total,TW_DATASETS,TW_CASH_SCHEMA,taiwan_rows
from app.services.multifactor import annual_rows,rated,rated_many
from app.services.freshness import local_now

TODAY=date(2026,11,9)
METRIC={'code':'CashFlowStatement','unit':'新台幣仟元'}
CATALOG='<a class="compareClass companyClass ysoClass" name="CashFlowStatement" label="新台幣仟元">● 現金流量表(累計)</a>'
SYMBOLS=['2330.TW','2412.TW','6488.TWO','2886.TW']


def report(symbols=SYMBOLS,values=None,year=2025,scope='合併',label='發放現金股利',unit='新台幣仟元'):
    if values is None:values=['(100,000)','(20,000)','(30,000)','0'][:len(symbols)]
    headers=''.join(f'<th>{scope}<br>{s.split(".")[0]} 測試公司<br>({"上櫃" if s.endswith(".TWO") else "上市"}產業)</th>' for s in symbols)
    cells=''.join(f'<td>{v}</td>' for v in values)
    return f'''<input name="yearseason" value="{year}4"><input name="reportName" value="現金流量表(累計)">
    <p>(金額單位：{unit})</p><table><thead><tr><th rowspan="2">會計項目</th><th colspan="{len(symbols)}">{year}Q4</th></tr>
    <tr>{headers}</tr></thead><tbody><tr><td>籌資活動之現金流量</td>{'<td></td>'*len(symbols)}</tr>
    <tr><td>{label}</td>{cells}</tr></tbody></table>'''


def seed_catalog():put('cashflow:catalog',{'at':time.time(),'metric':METRIC})


def test_catalog_discovers_only_exact_cash_statement_family_and_units():
    assert catalog(CATALOG)==METRIC
    for html in [CATALOG.replace('companyClass',''),CATALOG.replace('現金流量表','綜合損益表'),CATALOG.replace('新台幣仟元','美元'),CATALOG+CATALOG.replace('CashFlowStatement','DifferentCode')]:
        with pytest.raises(ValueError):catalog(html)


def test_batch_request_contains_only_fixed_codes_and_annual_q4():
    result=fields(SYMBOLS,2025,METRIC)
    assert result['companyId']==['2330','2412','6488','2886'] and result['ys']=='20254'
    assert result['quarter']=='true' and result['compareItem']=='CashFlowStatement'
    for symbols in [['2330.TW','2330.TWO'],['0050.TW','bad*'],['2330.TW']*21]:
        with pytest.raises(ValueError):fields(symbols,2025,METRIC)


def test_tw_two_financial_sector_and_zero_have_separate_column_bound_amounts():
    rows,issues=parse(report(),SYMBOLS,2025,TODAY,METRIC)
    assert not issues
    assert [rows[s]['cash_dividends_paid'] for s in SYMBOLS]==[100000000,20000000,30000000,0]
    evidence=rows['6488.TWO']['field_sources']['cash_dividends_paid']
    assert evidence['reported_value']==-30000 and evidence['multiplier']==1000 and evidence['scope']=='consolidated'
    assert evidence['period_start']=='2025-01-01' and evidence['period_end']=='2025-12-31'
    assert 'companyId=6488' in evidence['url'] and evidence['unit']=='TWD'


@pytest.mark.parametrize('old,new',[
 ('value="20254"','value="20253"'),('現金流量表(累計)','資產負債表'),
 ('新台幣仟元','美元'),('value="20254"','value="20244"'),
])
def test_wrong_report_period_kind_or_unit_rejected(old,new):
    with pytest.raises(ValueError):parse(report().replace(old,new),SYMBOLS,2025,TODAY,METRIC)


def test_yearseason_q4_notation_and_taiwan_currency_variants():
    for unit in ('新台幣千元','新臺幣仟元'):
        rows,issues=parse(report(unit=unit).replace('value="20254"','value="2025Q4"'),SYMBOLS,2025,TODAY,METRIC)
        assert rows['2330.TW']['cash_dividends_paid']==100000000


def test_missing_identity_parent_only_and_wrong_market_not_inferred():
    rows,issues=parse(report(scope='個體'),SYMBOLS,2025,TODAY,METRIC)
    assert not rows and set(issues)==set(SYMBOLS)
    rows,issues=parse(report(['2412.TW'],['(20,000)']),['2330.TW'],2025,TODAY,METRIC)
    assert not rows and '2330.TW' in issues
    rows,issues=parse(report(['2330.TW'],['(20,000)']),['2330.TWO'],2025,TODAY,METRIC)
    assert not rows and '2330.TWO' in issues


@pytest.mark.parametrize('label',['應付股利','支付利息及股利','支付予非控制權益之股利','宣告現金股利','股利收入'])
def test_wrong_dividend_concepts_never_fill_cash_outflow(label):
    rows,_=parse(report(label=label),SYMBOLS,2025,TODAY,METRIC)
    assert not rows


def test_dash_is_missing_but_explicit_zero_is_available():
    rows,issues=parse(report(values=['-','—','','0']),SYMBOLS,2025,TODAY,METRIC)
    assert set(rows)=={'2886.TW'} and rows['2886.TW']['cash_dividends_paid']==0 and len(issues)==3


def test_conflicting_duplicate_totals_preserve_missing_for_that_company():
    html=report()+report(values=['(99,000)','(20,000)','(30,000)','0'])
    rows,issues=parse(html,SYMBOLS,2025,TODAY,METRIC)
    assert '2330.TW' not in rows and len(rows)==3 and '衝突' in issues['2330.TW']


def test_conflicting_units_and_unsafe_number_rejected():
    with pytest.raises(ValueError):parse(report()+'<p>金額單位：美元</p>',SYMBOLS,2025,TODAY,METRIC)
    with pytest.raises(ValueError):parse(report(values=['10,00','1','2','3']),SYMBOLS,2025,TODAY,METRIC)
    assert number('（１，２３４）')==-1234
    assert number('0')==0 and number('—') is None


def test_merged_cell_bounds_and_scripts_not_report_evidence():
    with pytest.raises(ValueError):parse(report().replace('colspan="4"','colspan="100000"'),SYMBOLS,2025,TODAY,METRIC)
    with pytest.raises(ValueError):parse('<script>'+report()+'</script>',SYMBOLS,2025,TODAY,METRIC)


def test_finmind_new_exact_labels_include_units_and_never_sum_ytd():
    records=[{'stock_id':'2330','date':'2025-12-31','origin_name':'支付予本公司業主之股利','value':-500}]
    records.append({**records[0],'date':'2025-09-30','value':-300})
    assert paid_dividend_total(records,'2330','2025-12-31')==500
    row=taiwan_rows('2330.TW',{TW_DATASETS[2]:records},TODAY)['2025']
    assert row['cash_dividends_paid']==500
    assert row['field_sources']['cash_dividends_paid']['unit']=='TWD'


def test_automatic_backup_used_by_all_users_and_bulk_but_private_and_existing_zero_win():
    automatic=parse(report(['2330.TW'],['(100)']),['2330.TW'],2025,TODAY,METRIC)[0]['2330.TW']
    put('cashflow:official:2330.TW',{'rows':{'2025':automatic}})
    put('annual:shared:2330.TW',{'rows':{'2025':{'operating_cash_flow':300000,'capital_expenditure':50000,'currency':'TWD'}}})
    assert annual_rows('public','2330.TW')['2025']['cash_dividends_paid']==100000
    put('annual:Ualice:2330.TW',{'2025':{'cash_dividends_paid':777,'provenance':'user_import'}})
    assert annual_rows('Ualice','2330.TW')['2025']['cash_dividends_paid']==777
    assert annual_rows('Ubob','2330.TW')['2025']['cash_dividends_paid']==100000
    put('annual:shared:2330.TW',{'rows':{'2025':{'cash_dividends_paid':0}}})
    assert annual_rows('public','2330.TW')['2025']['cash_dividends_paid']==0


def test_worker_uses_batch_for_both_markets_and_preserves_data_on_failure(monkeypatch):
    import jobs.refresh_cash_dividends as job
    seed_catalog()
    loader=Mock(side_effect=lambda path,**kw:report(SYMBOLS,year=int(kw['form']['ys'][:4])))
    monkeypatch.setattr(job,'request',loader)
    first=job.run(SYMBOLS,max_requests=1,years=1)
    assert first['cash_requests']==1 and first['updated_fields']==4
    assert get('cashflow:official:6488.TWO')['rows']['2025']['cash_dividends_paid']==30000000
    assert job.run(SYMBOLS,max_requests=1,years=1)['cash_requests']==0
    for s in SYMBOLS:put(f'cashflow:state:{s}:2025',{'next_attempt':0})
    loader.side_effect=requests.ReadTimeout('secret')
    failed=job.run(SYMBOLS,max_requests=1,years=1)
    assert failed['failed_feeds']==4
    assert get('cashflow:official:2330.TW')['rows']['2025']['cash_dividends_paid']==100000000
    assert 'secret' not in str(get('cashflow:state:2330.TW:2025'))


def test_cold_catalog_respects_request_budget_and_source_shared_cap(monkeypatch):
    import jobs.refresh_cash_dividends as job
    import app.services.data_queue as queue
    loader=Mock(return_value=CATALOG);monkeypatch.setattr(job,'request',loader)
    assert job.run(['2330'],max_requests=1)['cash_requests']==1
    assert get('cashflow:catalog')['metric']==METRIC and loader.call_count==1
    monkeypatch.setattr(job,'source_slot',lambda *args:False)
    assert job.run(['2330'],max_requests=1)['cash_requests']==0
    assert loader.call_count==1


def test_all_market_rotation_uses_persistent_universe_not_sample_csv(monkeypatch):
    import jobs.refresh_cash_dividends as job
    seed_catalog()
    monkeypatch.setattr(job,'member_users',lambda:[])
    put('universe:small:TW',{'complete':True,'rows':[{'symbol':f'{code}.TW'} for code in range(1000,1050)]})
    put('universe:small:TWO',{'complete':True,'rows':[{'symbol':f'{code}.TWO'} for code in range(6000,6020)]})
    calls=[]
    def load(path,**kwargs):
        form=kwargs['form'];calls.append(form)
        symbols=[code+('.TWO' if code.startswith('6') else '.TW') for code in form['companyId']]
        return report(symbols,['(1)']*len(symbols),year=int(form['ys'][:4]))
    monkeypatch.setattr(job,'request',load)
    for _ in range(4):
        result=job.run(max_requests=1,years=1)
        assert result['market_symbols']==70 and result['market_complete'] is True
    assert all(len(call['companyId'])<=20 for call in calls)
    assert set().union(*(set(call['companyId']) for call in calls))=={str(c) for c in range(1000,1050)}|{str(c) for c in range(6000,6020)}
    assert get('cashflow:official:6000.TWO')['rows']['2025']['cash_dividends_paid']==1000


def test_no_market_universe_is_not_claimed_as_complete(monkeypatch):
    import jobs.refresh_cash_dividends as job
    seed_catalog();loader=Mock();monkeypatch.setattr(job,'request',loader)
    result=job.run(max_requests=1)
    assert result['market_symbols']==0 and result['market_complete'] is False
    loader.assert_not_called()


def test_cash_status_recognizes_zero_and_missing_years():
    from app.services.query_fundamentals import cash_status
    put('cashflow:official:2330.TW',{'rows':{'2025':{'cash_dividends_paid':0}}})
    result=cash_status('2330.TW')
    assert result['available_years']==1 and result['total_years']==5
    assert result['years'][0]['state']=='available' and result['years'][0]['value']==0


def test_manual_source_probe_uses_only_two_read_only_requests_and_reports_each_company():
    from scripts.check_cash_dividends import probe
    loader=Mock(side_effect=[CATALOG,report()])
    result=probe(SYMBOLS,2025,loader)
    assert result['state']=='verified' and result['cash_requests']==2 and not result['database_written']
    assert result['rows']['6488.TWO']['cash_dividends_paid']==30000000
    assert result['observed']['period']==['20254']
    assert len(result['observed']['company_headers'])==4


def test_source_http_rejection_retains_old_snapshot_and_cools_shared_source(monkeypatch):
    import jobs.refresh_cash_dividends as job
    seed_catalog()
    response=Mock(status_code=429)
    monkeypatch.setattr(job,'request',Mock(side_effect=requests.HTTPError(response=response)))
    put('cashflow:official:2330.TW',{'rows':{'2024':{'cash_dividends_paid':123}}})
    result=job.run(['2330'],max_requests=2,years=1)
    assert result['cash_requests']==1 and result['failed_feeds']==1
    assert get('annual:source:mopsfin')['next_attempt']>time.time()
    assert get('cashflow:official:2330.TW')['rows']['2024']['cash_dividends_paid']==123
    assert job.run(['2330'])['cash_requests']==0


def test_five_year_coverage_becomes_computable_for_public_private_and_bulk():
    from app.services.multifactor import value_for
    paid={};annual={}
    for year in range(2021,2026):
        paid[str(year)]=parse(report(['2330.TW'],['(100)'],year=year),['2330.TW'],year,TODAY,METRIC)[0]['2330.TW']
        annual[str(year)]={'operating_cash_flow':300000,'capital_expenditure':50000,'currency':'TWD'}
    put('annual:shared:2330.TW',{'rows':annual});put('cashflow:official:2330.TW',{'rows':paid})
    quote={'symbol':'2330.TW','kind':'STOCK','currency':'TWD','price':100,'date':str(local_now().date()),'cached_at':time.time(),'warnings':[]}
    for result in [rated(quote,'public'),rated(quote,'Ualice'),rated_many([quote],'Ualice')[0]]:
        field=next(c for c in result['rating']['checks'] if c['metric']=='fcf_coverage')
        assert field['value']==2.5 and field['passed'] is True
        assert result['annual_rows']['2025']['field_sources']['cash_dividends_paid']['unit']=='TWD'


def test_query_background_cash_step_shares_two_request_budget(monkeypatch):
    from app.services.query_fundamentals import process_download,status
    from jobs import refresh_tw_financials,refresh_eps,refresh_annual,refresh_cash_dividends
    seed_catalog()
    monkeypatch.setattr(refresh_tw_financials,'run',Mock(return_value={'official_requests':0}))
    monkeypatch.setattr(refresh_eps,'run',Mock(return_value={'eps_requests':0}))
    cash=Mock(return_value={'cash_requests':1,'updated_fields':1})
    annual=Mock(return_value={'annual_requests':1,'updated_symbols':1})
    monkeypatch.setattr(refresh_cash_dividends,'run',cash);monkeypatch.setattr(refresh_annual,'run',annual)
    process_download('2330.TW')
    assert cash.call_args.kwargs['max_requests']==1 and annual.call_args.kwargs['max_requests']==1
    assert status('2330')['cash_requests']+status('2330')['annual_requests']==2


def test_finmind_master_backup_handles_market_transfer_and_reuses_cache(monkeypatch,tmp_path):
    import jobs.refresh_universe as universe
    import app.providers.bounded_http as http
    monkeypatch.chdir(tmp_path);monkeypatch.setenv('FINMIND_TOKEN','private-token')
    monkeypatch.setattr(universe,'snapshot',Mock(side_effect=RuntimeError('offline')))
    today=str(local_now().date())
    payload={'status':200,'data':[
        {'date':'2024-01-01','stock_id':'6488','stock_name':'環球晶','type':'emerging'},
        {'date':today,'stock_id':'6488','stock_name':'環球晶','type':'tpex'},
        {'date':today,'stock_id':'2330','stock_name':'台積電','type':'twse'}]}
    loader=Mock(return_value=payload);monkeypatch.setattr(http,'fetch_json',loader)
    universe.build();universe.build()
    assert loader.call_count==1
    assert get('universe:small:TWO')['rows']==[{'symbol':'6488.TWO','name':'環球晶'}]
    assert get('universe:small:TW')['rows']==[{'symbol':'2330.TW','name':'台積電'}]
    assert 'private-token' not in str(loader.call_args.args[1])


def test_annual_cash_status_renders_in_query_page(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from tests.test_improvements import quote
    from app.services.query_fundamentals import cash_status
    values=parse(report(['2330.TW'],['(100,000)']),['2330.TW'],2025,TODAY,METRIC)[0]
    put('cashflow:official:2330.TW',{'rows':{'2025':values['2330.TW']}})
    data=rated(quote(),'public')
    def request(method,url,**kwargs):
        if '/quote/' in url:body=data
        elif '/fundamentals/request/' in url:body={'state':'cached','symbol':'2330.TW','message':'已取得部分年度',
            'cash_dividend_status':cash_status('2330.TW')}
        elif url.endswith('/scan'):body={}
        else:raise AssertionError('Unexpected request '+url)
        response=Mock(status_code=200);response.json.return_value=body;return response
    monkeypatch.setattr(requests,'request',request)
    # The UI now probes maintenance before rendering forms. Stub this
    # separate GET request explicitly; keep production fail-closed behavior.
    maintenance=Mock(status_code=200)
    maintenance.json.return_value={'maintenance':False}
    monkeypatch.setattr(requests,'get',lambda url,**kwargs: maintenance)
    app=AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py'),default_timeout=20)
    app.run();app.button(key='FormSubmitter:query-分析').click().run()
    assert not app.exception
    assert any('年度現金股利支出總額（已有 1/5 年）'==item.label for item in app.expander)
    frames=[item.value for item in app.dataframe if '現金股利支出（元）' in item.value.columns]
    assert frames and frames[0].iloc[0]['現金股利支出（元）']==100000000


def test_numeric_data_rows_before_dividends_are_not_misread_as_company_headers():
    html=report(['2330.TW'],['(100)']).replace('<tr><td>發放現金股利',
        '<tr><td>借款</td><td>1234</td></tr><tr><td>借款其他</td><td>-</td></tr><tr><td>發放現金股利')
    rows,issues=parse(html,['2330.TW'],2025,TODAY,METRIC)
    assert not issues and rows['2330.TW']['cash_dividends_paid']==100000


def test_oversized_company_batch_shrinks_next_batch_without_immediate_retry(monkeypatch):
    import jobs.refresh_cash_dividends as job
    from app.providers.bounded_http import ResourceLimitError
    seed_catalog()
    loader=Mock(side_effect=ResourceLimitError());monkeypatch.setattr(job,'request',loader)
    first=job.run(SYMBOLS,max_requests=1,years=1)
    assert first['cash_requests']==1 and loader.call_count==1
    assert get('cashflow:batch_size')['value']==2
    for symbol in SYMBOLS:put(f'cashflow:state:{symbol}:2025',{'next_attempt':0})
    loader.side_effect=lambda path,**kw:report([c+('.TWO' if c=='6488' else '.TW') for c in kw['form']['companyId']],['(1)']*len(kw['form']['companyId']))
    second=job.run(SYMBOLS,max_requests=1,years=1)
    assert second['updated_fields']==2 and len(loader.call_args.kwargs['form']['companyId'])==2


def test_single_company_batch_still_alternates_priority_and_market(monkeypatch):
    import jobs.refresh_cash_dividends as job
    seed_catalog();put('cashflow:batch_size',{'value':1})
    monkeypatch.setattr(job,'member_users',lambda:[])
    monkeypatch.setattr(job,'requested',lambda:{'2330.TW':{},'2412.TW':{},'2303.TW':{}})
    put('universe:small:TW',{'complete':True,'rows':[{'symbol':'1101.TW'}]})
    put('universe:small:TWO',{'complete':True,'rows':[]})
    calls=[]
    def load(path,**kw):
        codes=kw['form']['companyId'];calls.append(codes)
        return report([c+'.TW' for c in codes],['(1)']*len(codes))
    monkeypatch.setattr(job,'request',load)
    job.run(max_requests=1,years=1);job.run(max_requests=1,years=1)
    assert calls[0][0] in ('2330','2412','2303') and calls[1]==['1101']


def test_live_catalog_blank_unit_is_discovered_and_report_still_verifies_units():
    html='<a name="CashflowStatement" label="" class="compareItem compareClass ysoClass companyClass">現金流量表(累計)</a>'
    metric=catalog(html)
    assert metric=={'code':'CashflowStatement','unit':''}
    assert fields(['2330.TW'],2025,metric)['ylabel']==''
    rows,_=parse(report(symbols=['2330.TW']),['2330.TW'],2025,TODAY,metric)
    assert rows['2330.TW']['cash_dividends_paid']==100000000
    with pytest.raises(ValueError):
        parse(report(symbols=['2330.TW'],unit='美元'),['2330.TW'],2025,TODAY,metric)


def test_global_catalog_failure_is_visible_for_every_unattempted_year():
    from app.services.query_fundamentals import cash_status
    put('cashflow:catalog_state',{'reason':'目錄核對失敗','next_attempt':time.time()+300})
    rows=cash_status('2330.TW')['years']
    assert all(r['state']=='failed' and r['reason']=='目錄核對失敗' and r['retry_after_seconds']>0 for r in rows)
    put('cashflow:official:2330.TW',{'rows':{'2025':{'cash_dividends_paid':0}}})
    assert cash_status('2330.TW')['years'][0]['state']=='available'


def test_cli_failure_exit_does_not_turn_empty_failed_batches_green():
    from jobs.refresh_cash_dividends import exit_code
    assert exit_code({'state':'failed'})==1
    assert exit_code({'state':'partial','failed_feeds':1,'updated_fields':0})==1
    assert exit_code({'state':'partial','failed_feeds':1,'updated_fields':2})==0
    assert exit_code({'state':'limited'})==0


def test_old_catalog_contract_cooldown_does_not_block_fixed_parser(monkeypatch):
    import jobs.refresh_cash_dividends as job
    put('cashflow:catalog_state',{'next_attempt':time.time()+3600,'error_code':'contract'})
    loader=Mock(return_value=CATALOG);monkeypatch.setattr(job,'request',loader)
    assert job.run(['2330'],max_requests=1)['cash_requests']==1
    loader.assert_called_once()


def test_captured_official_split_tables_bind_amount_to_company_and_year():
    from pathlib import Path
    html=(Path(__file__).parent/'fixtures/mopsfin_cashflow_2330_2025.html').read_text()
    metric={'code':'CashflowStatement','unit':''}
    rows,issues=parse(html,['2330.TW','2412.TW'],2025,TODAY,metric)
    assert rows['2330.TW']['cash_dividends_paid']==466779199000
    assert '2412.TW' in issues and '2412.TW' not in rows
    for corrupted in (html.replace('id="bodyTable"','id="otherTable"'),html.replace('2330 台積電','2412 中華電',1),html.replace('新台幣仟元','美元'),html.replace('投資活動之淨現金流入','其他活動之淨現金流入')):
        with pytest.raises(ValueError):parse(corrupted,['2330.TW'],2025,TODAY,metric)


def test_split_multiple_company_columns_keep_distinct_identity_and_zero():
    labels=['報表類別','會計科目','營業活動之淨現金流入(流出)','投資活動之淨現金流入(流出)','籌資活動之淨現金流入(流出)','發放現金股利']
    values=[['合併','合併'],['2330 台積電 (上市半導體業)','6488 測試公司 (上櫃業)'],['1','2'],['3','4'],['5','6'],['-100','0']]
    def table(rows):return '<table>'+''.join('<tr>'+''.join('<td>'+v+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    html='<input name="yearseason" value="2025Q4">'+''.join('<input name="reportName" value="'+v+'">' for v in values[1])+'<p>金額單位：新台幣仟元</p><div id="headTable">'+table([[v] for v in labels])+'</div><div id="bodyTable">'+table(values)+'</div>'
    rows,issues=parse(html,['2330.TW','6488.TWO'],2025,TODAY,{'code':'CashflowStatement','unit':''})
    assert not issues
    assert rows['2330.TW']['cash_dividends_paid']==100000
    assert rows['6488.TWO']['cash_dividends_paid']==0
    with pytest.raises(ValueError):parse(html.replace('<td>-100</td>',''),['2330.TW','6488.TWO'],2025,TODAY,METRIC)
