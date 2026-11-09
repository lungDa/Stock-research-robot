import time,json
from datetime import timedelta,date
from unittest.mock import Mock
import pytest,requests
from app.db import put,get
from app.services.freshness import local_now
from app.providers.annual_free import TW_DATASETS
from app.providers.tw_daily import parse


def price_rows(symbol='2330'):
    today=local_now().date()
    return [{'stock_id':symbol,'date':str(today-timedelta(days=i)),'close':100+i/100,'Trading_Volume':1000} for i in range(150) if (today-timedelta(days=i)).weekday()<5]


def test_existing_finmind_prices_recover_stale_official_quote_without_http(monkeypatch):
    from app.services import research as svc
    now=time.time();previous={'symbol':'2330.TW','name':'台積電','kind':'STOCK','price':90,'date':'2026-01-01','cached_at':now-4000,'data_status':'stale'}
    put('quote:2330.TW',previous)
    put('annual:feed:2330.TW:'+TW_DATASETS[4],{'at':now,'status':'ok','records':price_rows()})
    loader=Mock(side_effect=AssertionError('No external requests allowed'))
    monkeypatch.setattr(svc,'fetch',loader)
    result=svc.research('2330')
    assert result['source']=='FinMind / TaiwanStockPrice' and result['ma60'] is not None
    assert result['date']==price_rows()[0]['date'] and result['cached_at']==now
    assert result['data_status']!='stale'
    loader.assert_not_called()
    assert svc.cached_quote('2330')['date']==result['date']
    assert svc.quotes_for(['2330.TW'])[0]['date']==result['date']


@pytest.mark.parametrize('age,shift',[(37*3600,0),(0,20)])
def test_old_download_or_old_price_never_refreshes_stale_quote(age,shift):
    from app.providers.tw_daily import shared
    rows=price_rows()
    for r in rows:r['date']=str(date.fromisoformat(r['date'])-timedelta(days=shift))
    put('annual:feed:2330.TW:'+TW_DATASETS[4],{'at':time.time()-age,'records':rows})
    assert shared('2330.TW',get) is None


def test_price_parser_rejects_conflict_and_future_does_not_become_latest():
    today=local_now().date();rows=price_rows()
    future={**rows[0],'date':str(today+timedelta(days=1)),'close':999}
    result=parse('2330.TW',rows+[future],today,time.time())
    assert result['price']!=999
    with pytest.raises(ValueError):parse('2330.TW',rows+[{**rows[0],'close':999}],today,time.time())


def test_backup_worker_downloads_short_window_once_and_keeps_token_out_of_params(monkeypatch):
    import jobs.refresh_tw_prices as job
    monkeypatch.setenv('FINMIND_TOKEN','private-token')
    loader=Mock(return_value={'status':200,'data':price_rows()});monkeypatch.setattr(job,'fetch_json',loader)
    first=job.run(['2330'],1)
    assert first['tw_price_requests']==1 and first['updated_symbols']==1
    assert get('twdaily:quote:2330.TW')['history_count']>=60
    assert job.run(['2330'],1)['tw_price_requests']==0
    params=loader.call_args.args[1]
    assert params['dataset']=='TaiwanStockPrice' and 'private-token' not in str(params)
    assert (date.fromisoformat(params['end_date'])-date.fromisoformat(params['start_date'])).days==160
    assert loader.call_args.kwargs['headers']=={'Authorization':'Bearer private-token'}
    assert loader.call_args.kwargs['max_bytes']==262144


@pytest.mark.parametrize('code,cools',[(400,False),(429,True)])
def test_backup_rejection_preserves_quote_and_obeys_source_cooldown(monkeypatch,code,cools):
    import jobs.refresh_tw_prices as job
    monkeypatch.setenv('FINMIND_TOKEN','fixture')
    monkeypatch.setattr(job,'fetch_json',lambda *a,**k:{'status':code})
    put('twdaily:quote:2330.TW',{'keep':1})
    assert job.run(['2330'])['failed_feeds']==1
    assert get('twdaily:quote:2330.TW')=={'keep':1}
    assert bool(get('annual:source:finmind'))==cools


def test_query_uses_pdf_and_price_recovery_before_failed_official_path(monkeypatch):
    from app.services.query_fundamentals import process_download,status
    from jobs import refresh_eps,refresh_tw_prices,refresh_tw_financials,refresh_annual
    put('mopsfin:feed:2330.TW:eps',{'status':'failed'})
    pdf=Mock(return_value={'state':'updated','eps_requests':1})
    daily=Mock(return_value={'tw_price_requests':1})
    official=Mock();annual=Mock()
    monkeypatch.setattr(refresh_eps,'run',pdf);monkeypatch.setattr(refresh_tw_prices,'run',daily)
    monkeypatch.setattr(refresh_tw_financials,'run',official);monkeypatch.setattr(refresh_annual,'run',annual)
    process_download('2330.TW')
    assert pdf.call_count==1 and daily.call_count==1
    official.assert_not_called();annual.assert_not_called()
    result=status('2330')
    assert result['eps_requests']+result['tw_price_requests']==2


def test_ttm_roe_rebuilt_from_persisted_periods_even_if_shared_trailing_absent():
    from app.services.multifactor import rated
    today=local_now().date()
    end=today.replace(day=1,month=((today.month-1)//3)*3+1)-timedelta(days=1)
    dates=[];q=(end.month-1)//3
    for i in range(4):
        y,n=divmod(end.year*4+q-i,4);dates.append(f'{y}-{("03-31","06-30","09-30","12-31")[n]}')
    oldest=date.fromisoformat(dates[-1]);start=date(oldest.year,(oldest.month-1)//3*3+1,1)
    put('annual:feed:2330.TW:'+TW_DATASETS[0],{'records':[{'stock_id':'2330','date':d,'type':'IncomeAfterTaxes','value':20} for d in dates]})
    put('annual:feed:2330.TW:'+TW_DATASETS[1],{'records':[{'stock_id':'2330','date':str(d),'type':'Equity','value':100} for d in [start-timedelta(days=1),end]]})
    data={'symbol':'2330.TW','kind':'STOCK','currency':'TWD','price':100,'date':str(today),'cached_at':time.time(),'warnings':[]}
    result=rated(data,'public')
    assert result['roe']==.8 and result['trailing_details']['roe_ttm_pct']['period_end']==str(end)
    assert result['eps'] is None  # No substitution or unverified EPS summation.


@pytest.mark.parametrize('exc,code',[(requests.ReadTimeout('token=secret'),'timeout'),(requests.ConnectionError('secret'),'connection'),(json.JSONDecodeError('secret','x',0),'json'),(ValueError('Annual unit mismatch'),'contract'),(ValueError('secret remote body'),'contract')])
def test_diagnostic_categories_never_persist_exception_secrets(exc,code):
    from app.providers.source_errors import describe
    result=describe(exc,'EPS解析')
    assert result['error_code']==code and 'secret' not in str(result)


def test_mops_failure_identifies_download_stage_and_timeout(monkeypatch):
    import jobs.refresh_tw_financials as job
    from app.providers.mopsfin import parse_catalog
    catalog='<a class="compareClass" name="EPS" label="元">每股盈餘</a><a class="compareClass" name="ROE" label="%">權益報酬率</a>'
    put('mopsfin:catalog',{'at':time.time(),'metrics':parse_catalog(catalog)})
    put('mopsfin:company:2330.TW',{'at':time.time(),'display':'2330 台積電'})
    monkeypatch.setattr(job,'request',Mock(side_effect=requests.ReadTimeout('secret')))
    job.run(['2330'],max_requests=1)
    result=get('mopsfin:feed:2330.TW:eps')
    assert result['stage']=='年度eps下載' and result['error_code']=='timeout'
    assert 'secret' not in str(result)


def test_2330_official_pdf_transcribed_annual_cells_do_not_use_pretax_profit():
    # Transcribed text from TWSE company profile, retrieved via web 2026-11-09.
    # This verifies text interpretation; it is not a raw-PDF HTTP contract test.
    from app.providers.twse_eps import parse_texts
    identity='產製日期: 2026/11/09\n股票代號:2330'
    table='''第一季 半年度 前三季 全年度 每股盈餘 繼續營業單位稅前淨利(千元)
2021年 5.39 155,064,389 10.57 304,455,464 16.59 478,307,103 23.01 663,126,314
2022年 7.82 226,831,696 16.96 492,829,977 27.79 809,520,844 39.20 1,144,190,718
2023年 7.98 244,274,931 14.99 458,949,840 23.13 700,890,335 32.34 979,171,324
2024年 8.70 266,543,204 18.25 572,853,779 30.80 957,040,631 45.25 1,405,838,635
2025年 13.95 430,895,412 29.31 923,930,616 46.75 1,449,299,639 66.26 2,041,662,840'''
    rows=parse_texts([identity,table],'2330.TW',date(2026,11,9))['rows']
    assert rows['2025']['eps']==66.26 and rows['2021']['eps']==23.01 and len(rows)==5


def test_pdf_pe_uses_only_recognized_table_not_unrelated_numbers():
    from app.providers.twse_eps import parse_texts
    identity='產製日期: 2026/11/09\n股票代號:2330'
    annual='第一季 半年度 前三季 全年度 每股盈餘 淨利(千元)\n2025年 1 2 3 4 5 6 66.26 99'
    page='11/9 999\n日期 本益比\n11/5 25.97 11/6 24.75\n月營收\n11/9 777'
    result=parse_texts([identity,annual,page],'2330.TW',date(2026,11,9))
    assert result['valuation']['pe']['value']==24.75 and result['valuation']['pe']['as_of']=='2026-11-06'
    assert 'valuation' not in parse_texts([identity,annual,page.replace('日期 本益比','未知欄名 本益比')],'2330.TW',date(2026,11,9))


def test_pdf_pe_backup_attaches_but_keeps_fresh_primary_valuation():
    from app.providers.fundamentals import attach
    today=str(local_now().date())
    backup={'value':20,'as_of':today,'source':'https://www.twse.com.tw/pdf/ch/2330_ch.pdf'}
    put('eps:official:2330.TW',{'valuation':{'pe':backup}})
    data={'symbol':'2330.TW','kind':'STOCK','warnings':[]}
    assert attach(data.copy())['pe']==20
    put('fundamentals:index:TW',{'2330':{'fields':{'pe':{'value':21,'as_of':today}}}})
    assert attach(data.copy())['pe']==21


def test_shared_backup_prefers_newest_price_day_not_first_source():
    from app.providers.tw_daily import shared
    today=local_now().date();rows=price_rows();newest=date.fromisoformat(rows[0]['date'])
    quote=parse('2330.TW',[r for r in rows if r['date']<str(newest)],today,time.time())
    put('twdaily:quote:2330.TW',quote)
    put('annual:feed:2330.TW:'+TW_DATASETS[4],{'at':time.time(),'records':rows})
    assert shared('2330.TW',get)['date']==str(newest)


def test_manual_diagnostic_continues_after_official_failure_without_leaking_token():
    from scripts.check_stock_sources import diagnose
    official=Mock(side_effect=requests.ReadTimeout('secret'))
    pdf=Mock(return_value={'rows':{'2025':{'eps':1}},'report_date':'2026-11-09'})
    prices=Mock(return_value={'status':200,'data':price_rows()})
    result=diagnose('2330',official,pdf,prices,'secret')
    assert result['requests']==3 and not result['ttm_eps_verified']
    assert result['sources']['mopsfin_failure']['error_code']=='timeout'
    assert result['sources']['annual_eps_pdf']['status']=='ok'
    assert result['sources']['finmind_prices']['ma60_available']
    assert 'secret' not in str(result)
