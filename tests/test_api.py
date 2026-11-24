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

def test_maintenance_blocks_public_private_and_webhook(monkeypatch):
    import app.api.server as server
    original_get=server.get
    monkeypatch.setattr(server,'get',lambda key,default=None: {'enabled':True} if key=='system:maintenance' else original_get(key,default))
    with TestClient(app) as c:
        assert c.get('/health').status_code==200
        assert c.get('/maintenance/status').json()=={'maintenance':True}
        for path in ('/public/scan','/watchlist','/quote/2412'):
            response=c.get(path)
            assert response.status_code==503
        assert c.post('/line/webhook',json={'events':[]}).status_code==503
        assert c.post('/auth/line/start',json={}).status_code==503


def test_signed_webhook_in_maintenance_gets_notice_without_running_command(monkeypatch):
    from unittest.mock import Mock
    import app.api.server as server
    from app.channels import commands
    from app.db import get,put
    put('system:maintenance',{'enabled':True})
    command=Mock();reply=Mock()
    monkeypatch.setattr(commands,'respond',command)
    monkeypatch.setattr(line,'reply',reply)
    event={'type':'message','webhookEventId':'maintenance-test','source':{'type':'user','userId':'Ualice'},
           'replyToken':'token','message':{'type':'text','text':'通知開啟'}}
    body,headers=signed({'events':[event]})
    with TestClient(app) as c:
        assert c.post('/line/webhook',content=body,headers=headers).status_code==200
    command.assert_not_called()
    assert '維護中' in reply.call_args.args[1]
    assert get('event:maintenance-test') is None
    assert get('system:maintenance')['enabled'] is True


def test_defensive_research_route_requires_login_and_reports_missing_data():
    with TestClient(app) as client:
        route = '/defensive/research/2317.TW'
        assert client.get(route).status_code == 401
        assert client.get(route + '?min_pairs=1', headers=A).status_code == 422
        assert client.get('/defensive/research/AAPL', headers=A).status_code == 400
        response = client.get(route, headers=A)
        assert response.status_code == 200
        assert response.json() == {'state': 'calendar_missing', 'symbol': '2317.TW'}


def test_defensive_market_ranking_reads_snapshot_with_authentication():
    from app.db import put

    with TestClient(app) as client:
        route = '/defensive/market-ranking'
        assert client.get(route).status_code == 401
        assert client.get(route, headers=A).json() == {'state': 'ranking_missing'}
        snapshot = {'state': 'evaluated', 'as_of': '2026-11-24'}
        put('defensive:market_ranking', snapshot)
        assert client.get(route, headers=A).json() == snapshot
