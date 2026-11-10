import time
from urllib.parse import urlparse,parse_qs
import pytest
from fastapi.testclient import TestClient
from app.api.server import app
from app.api import line_login as auth
from app.config import settings
from app.db import get,put
from app.services.accounts import register,password_matches,member_users
U='U'+'1'*32;V='U'+'2'*32

@pytest.fixture
def configured(monkeypatch):
    for key,value in dict(login_channel_id='12345',login_channel_secret='test-secret',
        login_callback='https://testserver/auth/line/callback',public_app_url='https://frontend.example',api_public_url='https://testserver').items():monkeypatch.setattr(settings,key,value)

def preauth(user):
    register(user,'測試使用者');token='t'+user[1:]+user[1:]
    put('auth:session:'+auth.digest(token),{'user':user,'expires':time.time()+600,'stage':'password'})
    return {'Authorization':'Bearer '+token}

def activate(client,user=U,new='12345678'):
    headers=preauth(user)
    assert client.post('/auth/password/verify',headers=headers,json={'password':'0000'}).status_code==403
    key='auth:session:'+auth.digest(headers['Authorization'].removeprefix('Bearer '))
    session=get(key);session['stage']='setup_password';put(key,session)
    assert client.post('/auth/password/change',headers=headers,json={'new_password':new}).status_code==200
    return headers

def test_public_works_private_denied_before_login(monkeypatch):
    import app.api.public as public
    monkeypatch.setattr(public,'cached_quote',lambda s:{'symbol':s,'kind':'UNKNOWN','price':100,'cached_at':time.time(),'date':'2026-11-06'})
    with TestClient(app) as c:
        assert c.get('/public/quote/2330').status_code==200
        assert c.get('/public/scan').status_code==200
        assert c.get('/watchlist').status_code==401
        assert c.put('/strategy',json={}).status_code==401

def test_default_then_forced_change_eight_digits(configured):
    with TestClient(app) as c:
        h=preauth(U)
        assert c.get('/watchlist',headers=h).status_code==403
        assert c.post('/auth/password/change',headers=h,json={'new_password':'12345678'}).status_code==403
        r=c.post('/auth/password/verify',headers=h,json={'password':'0000'})
        assert r.status_code==403
        key='auth:session:'+auth.digest(h['Authorization'].removeprefix('Bearer '))
        session=get(key);session['stage']='setup_password';put(key,session)
        assert c.get('/watchlist',headers=h).status_code==403
        for bad in ['0000','abcdefgh','123456789','１２３４５６７８']:
            assert c.post('/auth/password/change',headers=h,json={'new_password':bad}).status_code==400
        assert c.post('/auth/password/change',headers=h,json={'new_password':'00112233'}).status_code==200
        assert c.get('/watchlist',headers=h).status_code==200
        record=get('member:'+U)
        assert not record['password_change_required']
        assert record['password_hash']!='00112233' and password_matches('00112233',record['password_hash'])
        register(U,'新名稱')  # 再次綁定不能重設密碼
        assert password_matches('00112233',get('member:'+U)['password_hash'])

def test_people_passwords_and_data_isolated(configured):
    with TestClient(app) as c:
        a=activate(c,U,'12345678');b=activate(c,V,'87654321')
        assert c.post('/watchlist',headers=a,json={'symbol':'2330'}).status_code==200
        assert c.get('/watchlist',headers=b).json()==[]
        config=c.get('/strategy',headers=a).json();config['daily_cap']=2
        c.put('/strategy',headers=a,json=config)
        assert c.get('/strategy',headers=b).json()['daily_cap']==3
        fresh=preauth(U)
        assert c.post('/auth/password/verify',headers=fresh,json={'password':'87654321'}).status_code==403
        assert c.post('/auth/password/verify',headers=fresh,json={'password':'12345678'}).json()['stage']=='active'

def test_change_password_invalidates_other_sessions(configured):
    with TestClient(app) as c:
        a=activate(c)
        other='z'*48
        member=get('member:'+U)
        put('auth:session:'+auth.digest(other),{'user':U,'stage':'active','password_version':member['password_version'],'expires':time.time()+600})
        b={'Authorization':'Bearer '+other}
        assert c.get('/watchlist',headers=b).status_code==200
        assert c.post('/auth/password/change',headers=a,json={'current_password':'12345678','new_password':'87654321'}).status_code==200
        assert c.get('/watchlist',headers=b).status_code==403
        assert c.get('/watchlist',headers=a).status_code==200
        c.post('/auth/logout',headers=a)
        assert c.get('/watchlist',headers=a).status_code==403

def test_oauth_state_cookie_pkce_nonce_and_one_time_handoff(configured,monkeypatch):
    calls=[]
    def line(url,data):
        calls.append((url,data))
        if url.endswith('/token'):return {'id_token':'test-id-token'}
        return {'sub':U,'name':'測試','aud':'12345','iss':'https://access.line.me','exp':time.time()+600,'nonce':data['nonce']}
    monkeypatch.setattr(auth,'line_json',line)
    with TestClient(app,base_url='https://testserver') as c:
        start=c.post('/auth/line/start',json={}).json()
        begin=c.get(start['authorize_url'],follow_redirects=False)
        assert begin.status_code==303
        query=parse_qs(urlparse(begin.headers['location']).query)
        assert query['code_challenge_method']==['S256']
        assert 'HttpOnly' in begin.headers['set-cookie'] and 'Secure' in begin.headers['set-cookie']
        state=query['state'][0]
        # 無原瀏覽器cookie不能劫持callback。
        with TestClient(app,base_url='https://testserver') as stranger:
            assert stranger.get('/auth/line/callback',params={'state':state,'code':'fake'}).status_code==401
        callback=c.get('/auth/line/callback',params={'state':state,'code':'code'},follow_redirects=False)
        assert callback.status_code==303
        assert calls[0][1]['code_verifier']
        handoff=parse_qs(urlparse(callback.headers['location']).query)['login_code'][0]
        redeemed=c.post('/auth/redeem',json={'code':handoff})
        assert redeemed.status_code==200 and redeemed.json()['stage']=='setup_password'
        assert c.post('/auth/redeem',json={'code':handoff}).status_code==401
        assert c.get('/watchlist',headers={'Authorization':'Bearer '+redeemed.json()['token']}).status_code==403
        setup_headers={'Authorization':'Bearer '+redeemed.json()['token']}
        assert c.post('/auth/password/verify',headers=setup_headers,json={'password':'0000'}).status_code==400
        assert c.post('/auth/password/change',headers=setup_headers,json={'new_password':'12345678'}).status_code==200
        assert c.get('/watchlist',headers=setup_headers).status_code==200

def test_wrong_nonce_rejected(configured,monkeypatch):
    def line(url,data):
        return {'id_token':'fake'} if url.endswith('/token') else {'sub':U,'aud':'12345','iss':'https://access.line.me','nonce':'wrong','exp':time.time()+300}
    monkeypatch.setattr(auth,'line_json',line)
    with TestClient(app,base_url='https://testserver') as c:
        url=c.post('/auth/line/start',json={}).json()['authorize_url']
        q=parse_qs(urlparse(c.get(url,follow_redirects=False).headers['location']).query)
        assert c.get('/auth/line/callback',params={'state':q['state'][0],'code':'x'}).status_code==502
        assert not get('member:'+U)

def test_new_members_worker_identity_and_disabled(configured):
    register(U,'甲');assert U not in member_users()
    rec=get('member:'+U);rec['password_change_required']=False;put('member:'+U,rec)
    assert U in member_users()
    rec=get('member:'+U);rec['active']=False;put('member:'+U,rec)
    assert U not in member_users()
    with pytest.raises(PermissionError):register(U,'甲')

def test_legacy_key_not_bypass_new_login(configured):
    with TestClient(app) as c:
        assert c.get('/watchlist',headers={'Authorization':'Bearer '+'a'*24}).status_code==403

def test_public_refresh_budget_and_no_private_user_sources(monkeypatch):
    import app.api.public as public
    assert public.reserve_refresh() and public.reserve_refresh()
    assert not public.reserve_refresh()
    # 公開分級不採用任何人的年度匯入。
    put('annual:'+U+':2330.TW',{'2025':{'eps':999,'source_url':'https://private.example'}})
    monkeypatch.setattr(public,'cached_quote',lambda s:{'symbol':s,'kind':'STOCK','cached_at':time.time(),'date':'2026-11-06'})
    with TestClient(app) as c:
        result=c.get('/public/quote/2330').json()
        assert result['rating']['grade']=='資料不足'
        assert result['annual_sources']==[]

def test_password_attempt_limit(configured):
    with TestClient(app) as c:
        h=preauth(U)
        for _ in range(6):assert c.post('/auth/password/verify',headers=h,json={'password':'wrong'}).status_code==403
        assert c.post('/auth/password/verify',headers=h,json={'password':'0000'}).status_code==429
