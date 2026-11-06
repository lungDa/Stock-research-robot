import time
from datetime import date,timedelta
from app.db import get,put
from app.providers.fundamentals import parse,merge,attach,FEEDS
from jobs import refresh_fundamentals as job

TODAY=date.today().isoformat()

def row(**kw): return {'出表日期':TODAY,'公司代號':'2330','公司名稱':'台積電',**kw}
def base():
    return {'symbol':'2330.TW','kind':'UNKNOWN','eps':None,'roe':None,'pe':None,'yield':None,'warnings':[]}

def test_fund_classification_requires_explicit_type():
    d={'出表日期':TODAY,'基金代號':'0050','基金類型':'國內成分證券指數股票型基金'}
    assert parse(d,'TW','fund','https://x',0)[1]['fields']['kind']['value']=='ETF'
    d['基金類型']='國內成分證券交易所交易基金'
    assert parse(d,'TW','fund','https://x',0)[1]['fields']['kind']['value']=='ETF'
    d['基金類型']='指數投資證券ETN'
    assert 'kind' not in parse(d,'TW','fund','https://x',0)[1]['fields']

def test_roc_ytd_eps_and_missing():
    p=parse(row(年度='115',季別='3',**{'基本每股盈餘（元）':'-1.20'}),'TW','eps','https://x',0)
    assert p[1]['fields']['eps']['period']=='2026Q3'
    assert p[1]['fields']['eps']['value']==-1.2
    assert 'eps' not in parse(row(年度='115',季別='3'),'TW','eps','https://x',0)[1]['fields']

def test_invalid_quarter_code_date_rejected():
    assert parse(row(年度='115',季別='9'),'TW','eps','https://x',0) is None
    assert parse(row(公司代號='2330A'),'TW','valuation','https://x',0) is None
    assert parse(row(出表日期='bad'),'TW','valuation','https://x',0) is None

def test_tpex_fields_zero_yield_not_ttm():
    r={'Date':TODAY,'SecuritiesCompanyCode':'6488','CompanyName':'環球晶','PriceEarningRatio':'20.5','YieldRatio':'0'}
    merge('TWO',[r],'valuation','https://x',time.time())
    d=attach({**base(),'symbol':'6488.TWO'})
    assert d['kind']=='STOCK' and d['pe']==20.5
    assert d['yield'] is None
    assert d['fundamental_details']['official_yield']['value']==0

def test_roe_report_not_eligible():
    merge('TW',[row(**{'股東權益報酬率(%)':'30'})],'roe_report','https://x',0)
    d=attach(base())
    assert d['roe'] is None
    assert d['fundamental_details']['reported_roe']['value']==.3

def test_old_period_cannot_replace_newer_eps():
    for quarter,value in [('3','20'),('2','10')]:
        merge('TW',[row(年度='115',季別=quarter,**{'基本每股盈餘（元）':value})],'eps','https://x',0)
    assert attach(base())['eps']==20

def test_expired_valuation_does_not_reuse_quote_value():
    old=(date.today()-timedelta(days=15)).isoformat()
    merge('TW',[row(出表日期=old,PEratio='22')],'valuation','https://x',0)
    assert attach({**base(),'pe':12})['pe'] is None

def test_missing_warning_deduplicated():
    d=attach(attach(base()))
    assert sum(x.startswith('基本面尚缺：') for x in d['warnings'])==1

def test_worker_two_requests_cooldown_and_partial_merge(monkeypatch):
    calls=[]
    monkeypatch.setattr(job,'FEEDS',[('TW','eps','https://1'),('TWO','eps','https://2')])
    def fetch(url,**kwargs):
        calls.append(kwargs)
        return {'records':[row(年度='115',季別='3',**{'基本每股盈餘（元）':'4'})],'complete':False}
    monkeypatch.setattr(job,'fetch_json',fetch)
    job.run();job.run()
    assert len(calls)==2
    assert all(c['max_bytes']==1048576 and c['seconds']==6 and c['array'] for c in calls)
    assert get('fundamentals:feed:https://1')['complete'] is False
    assert attach(base())['eps']==4

def test_worker_failure_keeps_data_and_rotates(monkeypatch):
    merge('TW',[row(PEratio='20')],'valuation','https://x',0)
    monkeypatch.setattr(job,'fetch_json',lambda *a,**k: (_ for _ in ()).throw(TimeoutError()))
    results=job.run()
    assert len(results)==2
    assert get('fundamentals:cursor')['value']==2
    assert attach(base())['pe']==20
