import json,base64,hmac,hashlib
from fastapi.testclient import TestClient
from app.api.server import app
from app.channels import line
A={'Authorization':'Bearer aaaaaaaaaaaaaaaaaaaaaaaa'}
B={'Authorization':'Bearer bbbbbbbbbbbbbbbbbbbbbbbb'}
def signed(payload):
    body=json.dumps(payload).encode()
    signature=base64.b64encode(hmac.new(b'test-secret',body,hashlib.sha256).digest()).decode()
    return body,{'x-line-signature':signature}
def test_access_control():
    with TestClient(app) as c:
        assert c.get('/watchlist').status_code==401
        assert c.get('/watchlist',headers={'Authorization':'Bearer wrong'}).status_code==403
        c.post('/watchlist',headers=A,json={'symbol':'AAPL'})
        assert c.get('/watchlist',headers=B).json()==[]
        assert c.get('/watchlist',headers=A).json()==['AAPL']
def test_signature_and_empty_verification():
    with TestClient(app) as c:
        assert c.post('/line/webhook',json={'events':[]}).status_code==401
        body,headers=signed({'events':[]})
        assert c.post('/line/webhook',content=body,headers=headers).status_code==200
        assert c.post('/line/webhook',content=body+b' ',headers=headers).status_code==401
def test_redelivery_not_replied_twice(monkeypatch):
    calls=[];monkeypatch.setattr(line,'reply',lambda *args:calls.append(args))
    event={'type':'message','webhookEventId':'1','source':{'type':'user','userId':'Ualice'},'replyToken':'token','message':{'type':'text','text':'追蹤 AAPL'}}
    body,headers=signed({'events':[event]})
    with TestClient(app) as c:
        assert c.post('/line/webhook',content=body,headers=headers).status_code==200
        assert c.post('/line/webhook',content=body,headers=headers).status_code==200
    assert len(calls)==1
def test_one_event_failure_does_not_stop_next(monkeypatch):
    calls=[]
    def reply(token,text):
        if token=='fail': raise RuntimeError('network')
        calls.append(token)
    monkeypatch.setattr(line,'reply',reply)
    events=[{'type':'message','webhookEventId':str(i),'source':{'type':'user','userId':'Ualice'},'replyToken':token,'message':{'type':'text','text':'我的清單'}} for i,token in enumerate(['fail','ok'])]
    body,headers=signed({'events':events})
    with TestClient(app) as c: assert c.post('/line/webhook',content=body,headers=headers).status_code==503
    assert calls==['ok']
def test_quote_failure_keeps_health_alive(monkeypatch):
    import app.api.server as server
    def fail(*args): raise RuntimeError('provider down')
    monkeypatch.setattr(server,'research',fail)
    with TestClient(app) as c:
        assert c.get('/quote/AAPL',headers=A).status_code==503
        assert c.get('/health').status_code==200
