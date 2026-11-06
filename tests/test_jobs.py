from datetime import datetime,timezone
from app.db import put,get
from app.services.watchlist import toggle

def test_scan_continues_after_stock_failure(monkeypatch):
    import jobs.scan as scan
    monkeypatch.setattr(scan,'load',lambda:['2330.TW','2412.TW'])
    def fake(symbol,refresh):
        if symbol=='2330.TW': raise RuntimeError('bad stock')
        put('quote:2412.TW',{'cached_at':__import__('time').time(),'symbol':'2412.TW','name':'Microsoft','date':'2026-11-06','income':{'matched':False},'swing':{'matched':True}})
    monkeypatch.setattr(scan,'research',fake)
    scan.run(2,60)
    result=get('scan:latest')
    assert result['failed']==['2330.TW'] and result['fresh_count']==1
    assert len(result['swing'])==1

def setup_signals(monkeypatch):
    import jobs.notify as notify
    import time
    from app.services.watchlist import add
    toggle('Ualice',True);add('Ualice','2330')
    monkeypatch.setattr(notify,'quota',lambda:100)
    monkeypatch.setattr(notify,'cached_quote',lambda symbol:dict(symbol=symbol,name='測試',price=100,currency='TWD',date=notify.local_now().date().isoformat(),cached_at=time.time()))
    monkeypatch.setattr(notify,'rated',lambda d,u:{**d,'rating':{'grade':'買','score':90,'coverage':100,'checks':[]}})
    return notify

def test_signal_once_and_opt_in(monkeypatch):
    notify=setup_signals(monkeypatch);calls=[]
    monkeypatch.setattr(notify,'push',lambda *args:calls.append(args))
    notify.run();notify.run()
    assert len(calls)==1 and calls[0][0]=='Ualice'

def test_no_quota_no_push(monkeypatch):
    notify=setup_signals(monkeypatch)
    monkeypatch.setattr(notify,'quota',lambda:0)
    def fail(*args):raise AssertionError('must not push')
    monkeypatch.setattr(notify,'push',fail)
    notify.run()

def test_push_retry_key_and_payload_stable(monkeypatch):
    notify=setup_signals(monkeypatch);calls=[]
    def uncertain(*args):calls.append(args);raise RuntimeError('timeout')
    monkeypatch.setattr(notify,'push',uncertain)
    notify.run();notify.run()
    assert len(calls)==1  # 60秒冷卻，不立即重試
    key='signal:state:Ualice:2330.TW';state=get(key)
    state['pending']['last_attempt']-=61;put(key,state)
    notify.run()
    assert len(calls)==2 and calls[0]==calls[1]

def test_independent_messages_daily_limit_and_no_unsubscribed(monkeypatch):
    notify=setup_signals(monkeypatch)
    monkeypatch.setattr(notify,'watches',lambda u:['2330.TW','2412.TW','2308.TW','2317.TW'])
    calls=[];monkeypatch.setattr(notify,'push',lambda *a:calls.append(a))
    notify.run();notify.run()
    assert len(calls)==3 and all(x[0]=='Ualice' for x in calls)
    assert all(sum(s in x[1] for s in ['2330','2412','2308','2317'])==1 for x in calls)

def test_downgrade_and_rule_change_baseline(monkeypatch):
    from app.services.multifactor import DEFAULT,config_hash
    notify=setup_signals(monkeypatch);calls=[]
    monkeypatch.setattr(notify,'push',lambda *a:calls.append(a))
    key='signal:state:Ualice:2330.TW'
    put(key,{'grade':'強力買','config_hash':config_hash(DEFAULT)})
    notify.run();assert len(calls)==1 and '強力買 → 買' in calls[0][1]
    put(key,{'grade':'觀望','config_hash':'old_rules'})
    notify.run();assert len(calls)==1
    assert get(key)['grade']=='買'

def test_missing_first_observation_silent(monkeypatch):
    notify=setup_signals(monkeypatch);calls=[]
    monkeypatch.setattr(notify,'rated',lambda d,u:{**d,'rating':{'grade':'資料不足','score':None,'coverage':0,'checks':[]}})
    monkeypatch.setattr(notify,'push',lambda *a:calls.append(a))
    notify.run();notify.run();assert not calls

def test_pending_expired_not_resent(monkeypatch):
    notify=setup_signals(monkeypatch);calls=[]
    key='signal:state:Ualice:2330.TW'
    put(key,{'pending':{'day':'2000-01-01','created_at':0,'grade':'買','config_hash':'x'}})
    monkeypatch.setattr(notify,'push',lambda *a:calls.append(a))
    notify.run();assert not calls and get(key)['uncertain_delivery']
