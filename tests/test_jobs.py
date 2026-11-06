from datetime import datetime,timezone
from app.db import put,get
from app.services.watchlist import toggle

def test_scan_continues_after_stock_failure(monkeypatch):
    import jobs.scan as scan
    monkeypatch.setattr(scan,'load',lambda:['AAPL','MSFT'])
    def fake(symbol,refresh):
        if symbol=='AAPL': raise RuntimeError('bad stock')
        put('quote:MSFT',{'cached_at':__import__('time').time(),'symbol':'MSFT','name':'Microsoft','date':'2026-11-06','income':{'matched':False},'swing':{'matched':True}})
    monkeypatch.setattr(scan,'research',fake)
    scan.run(2,60)
    result=get('scan:latest')
    assert result['failed']==['AAPL'] and result['fresh_count']==1
    assert len(result['swing'])==1

def test_digest_once_and_opt_in(monkeypatch):
    import jobs.notify as notify
    put('scan:latest',{'updated_at':datetime.now(timezone.utc).isoformat(),'income':[],'swing':[]})
    toggle('Ualice',True)
    calls=[]
    monkeypatch.setattr(notify,'quota',lambda:100)
    monkeypatch.setattr(notify,'push',lambda *args:calls.append(args))
    notify.run();notify.run()
    assert len(calls)==1 and calls[0][0]=='Ualice'

def test_no_quota_no_push(monkeypatch):
    import jobs.notify as notify
    put('scan:latest',{'updated_at':datetime.now(timezone.utc).isoformat()})
    toggle('Ualice',True)
    monkeypatch.setattr(notify,'quota',lambda:0)
    def fail(*args): raise AssertionError('must not push')
    monkeypatch.setattr(notify,'push',fail)
    notify.run()

def test_push_retry_key_stable(monkeypatch):
    import jobs.notify as notify
    put('scan:latest',{'updated_at':datetime.now(timezone.utc).isoformat()})
    toggle('Ualice',True);calls=[]
    monkeypatch.setattr(notify,'quota',lambda:100)
    def uncertain(user,text,key): calls.append(key);raise RuntimeError('timeout')
    monkeypatch.setattr(notify,'push',uncertain)
    notify.run();notify.run()
    assert len(calls)==2 and calls[0]==calls[1]
