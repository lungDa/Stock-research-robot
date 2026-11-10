"""LINE OAuth：個人密碼需在LINE認證後驗證，資料身分只取自驗證後的LINE ID token。"""
import base64,hashlib,hmac,json,re,secrets,time
from urllib.parse import urlencode,urlparse
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import RedirectResponse
import requests
from app.config import settings
from app.db import get,put,claim
from app.services.accounts import register,is_member,password_hash,password_matches
router=APIRouter(prefix='/auth')
COOKIE='__Host-lighthouse_oauth'

def digest(value):return hashlib.sha256(value.encode()).hexdigest()

def ready():
    return all((settings.login_channel_id,settings.login_channel_secret,settings.login_callback,settings.public_app_url,settings.api_public_url))

def ensure_ready():
    if not ready():raise HTTPException(503,'LINE登入尚未設定完成；公開查詢仍可使用')
    for u in (settings.login_callback,settings.public_app_url,settings.api_public_url):
        p=urlparse(u)
        if p.scheme!='https' or not p.hostname or p.query or p.fragment or p.username:raise HTTPException(503,'登入網址設定須為固定HTTPS網址')
    if settings.login_callback!=settings.api_public_url.rstrip('/')+'/auth/line/callback':raise HTTPException(503,'LINE callback設定不一致')

async def body_json(request,limit=4096):
    body=b''
    async for chunk in request.stream():
        body+=chunk
        if len(body)>limit:raise HTTPException(413,'內容過大')
    try:
        data=json.loads(body)
        if not isinstance(data,dict):raise ValueError()
        return data
    except ValueError:raise HTTPException(400,'格式錯誤')

def consume(kind,token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token):raise HTTPException(401,'登入連結無效或已過期')
    key='auth:'+kind+':'+digest(token);record=get(key,{})
    if record.get('expires',0)<time.time() or not claim(key+':used',{'at':time.time()}):raise HTTPException(401,'登入連結無效或已使用，請重新登入')
    return record

@router.get('/status')
def status():return {'line_login_ready':ready()}

@router.post('/line/start')
async def start(request:Request):
    ensure_ready();data=await body_json(request)
    # Streamlit轉送流量共用來源IP；每10分鐘最多10次啟動。
    host=request.client.host if request.client else 'unknown'
    bucket='auth:attempt:'+digest(host)+':'+str(int(time.time()//600))
    attempt=None
    for i in range(10):
        if claim(bucket+':'+str(i),{'at':time.time()}):attempt=i;break
    if attempt is None:raise HTTPException(429,'登入嘗試過多，請10分鐘後重試')
    ticket=secrets.token_urlsafe(32)
    put('auth:start:'+digest(ticket),{'expires':time.time()+120})
    return {'authorize_url':settings.api_public_url.rstrip('/')+'/auth/line/authorize?'+urlencode({'ticket':ticket})}

@router.get('/line/authorize')
def authorize(ticket:str):
    ensure_ready();consume('start',ticket)
    state=secrets.token_hex(32);nonce=secrets.token_hex(32)
    binding=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
    put('auth:flow:'+digest(state),{'expires':time.time()+600,'binding':digest(binding),'nonce':nonce,'verifier':verifier})
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    url='https://access.line.me/oauth2/v2.1/authorize?'+urlencode({'response_type':'code','client_id':settings.login_channel_id,
        'redirect_uri':settings.login_callback,'state':state,'nonce':nonce,'scope':'openid profile',
        'code_challenge':challenge,'code_challenge_method':'S256','bot_prompt':'normal'})
    response=RedirectResponse(url,status_code=303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
    response.set_cookie(COOKIE,binding,max_age=600,httponly=True,secure=True,samesite='lax',path='/')
    return response

def line_json(url,data):
    # 僅兩個固定官方端點；2秒連線、4秒讀取，回應上限64KiB。
    with requests.post(url,data=data,timeout=(2,4),stream=True,allow_redirects=False) as r:
        r.raise_for_status()
        if r.status_code!=200:raise ValueError('LINE未回傳成功')
        payload=b'';start=time.monotonic()
        for chunk in r.iter_content(4096):
            payload+=chunk
            if len(payload)>65536 or time.monotonic()-start>6:raise ValueError('登入回應超過預算')
        result=json.loads(payload)
        if not isinstance(result,dict):raise ValueError('LINE回應格式錯誤')
        return result

@router.get('/line/callback')
def callback(request:Request,state:str='',code:str='',error:str=''):
    ensure_ready()
    record=get('auth:flow:'+digest(state),{})
    cookie=request.cookies.get(COOKIE,'')
    if not cookie or not record.get('binding') or not hmac.compare_digest(record['binding'],digest(cookie)):
        raise HTTPException(401,'登入瀏覽器不符，請從原瀏覽器重新登入')
    record=consume('flow',state)
    if error or not code:raise HTTPException(400,'LINE登入取消或未完成')
    try:
        token=line_json('https://api.line.me/oauth2/v2.1/token',{'grant_type':'authorization_code','code':code,
            'redirect_uri':settings.login_callback,'client_id':settings.login_channel_id,
            'client_secret':settings.login_channel_secret,'code_verifier':record['verifier']})
        profile=line_json('https://api.line.me/oauth2/v2.1/verify',{'id_token':token['id_token'],
            'client_id':settings.login_channel_id,'nonce':record['nonce']})
        user=profile['sub']
        if not re.fullmatch(r'U[0-9a-fA-F]{32}',user):raise ValueError('LINE身分格式錯誤')
        if str(profile.get('aud'))!=settings.login_channel_id or profile.get('iss')!='https://access.line.me':raise ValueError('LINE簽發者不符')
        if profile.get('nonce')!=record['nonce'] or float(profile.get('exp',0))<=time.time():raise ValueError('LINE驗證已過期')
    except Exception:
        # 不記錄LINE token、authorization code或密碼。
        raise HTTPException(502,'LINE驗證暫未完成，請重新登入')
    try:register(user,profile.get('name','LINE使用者'))
    except PermissionError:raise HTTPException(403,'帳戶已停用')
    handoff=secrets.token_urlsafe(32)
    put('auth:handoff:'+digest(handoff),{'expires':time.time()+60,'user':user})
    response=RedirectResponse(settings.public_app_url.rstrip('/')+'/?'+urlencode({'login_code':handoff}),status_code=303,
        headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
    response.delete_cookie(COOKIE,path='/',secure=True,httponly=True,samesite='lax')
    return response

@router.post('/redeem')
async def redeem(request:Request):
    data=await body_json(request);code=data.get('code','')
    if not isinstance(code,str):raise HTTPException(400,'格式錯誤')
    handoff=consume('handoff',code)
    if not is_member(handoff['user']):raise HTTPException(403,'帳戶已停用')
    token=secrets.token_urlsafe(48)
    member=get('member:'+handoff['user'],{})
    stage='setup_password' if member.get('activation_pending') and not member.get('password_hash') else 'password'
    put('auth:session:'+digest(token),{'user':handoff['user'],'expires':time.time()+600,'stage':stage})
    return {'token':token,'expires_in':600,'stage':'password','name':get('member:'+handoff['user'],{}).get('name','LINE使用者')}

@router.post('/logout')
def logout(request:Request):
    value=request.headers.get('authorization','').removeprefix('Bearer ')
    if value:put('auth:session:'+digest(value),{'expires':0})
    return {'ok':True}

def session_info(request):
    token=request.headers.get('authorization','').removeprefix('Bearer ')
    key='auth:session:'+digest(token);session=get(key,{})
    if not token or session.get('expires',0)<=time.time() or not is_member(session.get('user','')):raise HTTPException(401,'登入已過期，請重新LINE登入')
    member=get('member:'+session['user'],{})
    if session.get('stage')=='active' and session.get('password_version')!=member.get('password_version',0):raise HTTPException(401,'密碼已變更，請重新LINE登入')
    return key,session,member

@router.get('/me')
def auth_me(request:Request):
    _,session,member=session_info(request)
    from app.api.security import is_admin
    return {'stage':session.get('stage'),'name':member.get('name','LINE使用者'),
            'password_change_required':member.get('password_change_required',True),
            'is_admin':session.get('stage')=='active' and is_admin(session['user'])}

@router.post('/password/verify')
async def verify_password(request:Request):
    key,session,member=session_info(request)
    data=await body_json(request);password=data.get('password','')
    if session.get('stage')!='password':raise HTTPException(400,'登入階段不符')
    bucket='auth:password-attempt:'+digest(session['user'])+':'+str(int(time.time()//600))
    if not any(claim(bucket+':'+str(i),{'at':time.time()}) for i in range(6)):raise HTTPException(429,'密碼嘗試過多，請10分鐘後重試')
    if not isinstance(password,str) or len(password)>128 or not password_matches(password,member.get('password_hash','')):raise HTTPException(403,'個人密碼錯誤')
    forced=member.get('password_change_required',True)
    session.update(stage='change_password' if forced else 'active',password_version=member.get('password_version',0),expires=time.time()+(600 if forced else 12*3600))
    put(key,session)
    return {'stage':session['stage'],'password_change_required':forced}

@router.post('/password/change')
async def change_password(request:Request):
    key,session,member=session_info(request)
    data=await body_json(request);new=data.get('new_password','')
    if not isinstance(new,str) or not re.fullmatch(r'[0-9]{8}',new):raise HTTPException(400,'新密碼必須剛好8位半形數字')
    if session.get('stage') not in ('active','change_password','setup_password'):raise HTTPException(403,'請先完成身分及密碼驗證')
    if session.get('password_version',0)!=member.get('password_version',0):raise HTTPException(401,'密碼已變更，請重新登入')
    if session.get('stage')=='setup_password' and (not member.get('activation_pending') or member.get('password_hash')):raise HTTPException(403,'帳戶已設定密碼，請重新登入')
    if session.get('stage')=='active':
        old=data.get('current_password','')
        if not isinstance(old,str) or len(old)>128 or not password_matches(old,member.get('password_hash','')):raise HTTPException(403,'目前密碼錯誤')
    elif session.get('stage')!='change_password':raise HTTPException(403,'請先驗證初始密碼')
    if password_matches(new,member.get('password_hash','')):raise HTTPException(400,'新密碼需與目前密碼不同')
    member.update(password_hash=password_hash(new),password_change_required=False,password_version=secrets.token_hex(16),activation_pending=False)
    put('member:'+session['user'],member)
    session.update(stage='active',password_version=member['password_version'],expires=time.time()+12*3600)
    put(key,session)
    return {'stage':'active','password_change_required':False}
