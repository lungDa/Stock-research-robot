import asyncio,json,logging,time
from fastapi import FastAPI,Depends,HTTPException,Request,BackgroundTasks
from pydantic import BaseModel,Field
from app.db import init_db,get,claim,put
from app.api.security import current_user,current_admin,is_admin
from app.services.research import research
from app.services.watchlist import watches,add,remove,toggle
from app.channels import line,commands
from app.config import settings
from contextlib import asynccontextmanager
log=logging.getLogger(__name__)
@asynccontextmanager
async def lifespan(app):
    init_db()
    settings.users  # 設定錯誤在啟動時顯示
    from app.day_trader.admin_bootstrap import provision_designated_admin_from_env
    provision_designated_admin_from_env()
    yield
app=FastAPI(title='股海燈塔 API',lifespan=lifespan)
from app.api.line_login import router as login_router
app.include_router(login_router)
from app.api.public import router as public_router
app.include_router(public_router)
from app.trading.api import router as paper_router
app.include_router(paper_router)
# 單一程序限制同時向行情商發出請求；免費部署維持一個 worker。
from app.api.limits import quote_lock
class Symbol(BaseModel): symbol:str=Field(max_length=25)
class Notice(BaseModel): enabled:bool
@app.get('/health')
def health(): return {'status':'ok'}
@app.get('/me')
def me(user=Depends(current_user)): return {'user':user,'is_admin':is_admin(user)}

@app.get('/admin/status')
def admin_status(user=Depends(current_admin)):
    from app.services.operations import overview
    return overview()

@app.get('/ready')
def ready():
    from app.db import Session
    from sqlalchemy import text
    try:
        with Session() as session:session.execute(text('SELECT 1'))
        return {'status':'ok','database':'ok'}
    except Exception:raise HTTPException(503,'資料庫暫不可用')
@app.get('/watchlist')
def watchlist(user=Depends(current_user)): return watches(user)
@app.post('/watchlist')
def watch_add(body:Symbol,user=Depends(current_user)):
    try: return {'symbol':add(user,body.symbol)}
    except ValueError as e: raise HTTPException(400,str(e))
@app.delete('/watchlist/{symbol}')
def watch_remove(symbol:str,user=Depends(current_user)):
    try: remove(user,symbol); return {'ok':True}
    except ValueError as e: raise HTTPException(400,str(e))
@app.post('/notifications')
def notifications(body:Notice,user=Depends(current_user)):
    toggle(user,body.enabled)
    if not body.enabled:
        from app.services.market_recommendations import enable
        enable(user,False)
    return {'ok':True}
@app.get('/quote/{symbol}')
async def quote(symbol:str,user=Depends(current_user)):
    try:
        async with quote_lock:
            data=await asyncio.to_thread(research,symbol)
            from app.services.multifactor import rated
            return await asyncio.to_thread(rated,data,user)
    except ValueError as e: raise HTTPException(400,str(e))
    except Exception:
        log.exception('quote failed'); raise HTTPException(503,'行情暫不可用，請稍後再試')

@app.post('/fundamentals/prepare/{symbol}')
async def prepare_fundamentals(symbol:str,user=Depends(current_user)):
    from app.services.query_fundamentals import prepare
    try:
        async with quote_lock:return await asyncio.to_thread(prepare,symbol)
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.post('/fundamentals/request/{symbol}')
def request_fundamentals(symbol:str,background_tasks:BackgroundTasks,user=Depends(current_user)):
    from app.api.public import request_fundamentals as request_shared
    return request_shared(symbol,background_tasks)

@app.get('/fundamentals/status/{symbol}')
def download_status(symbol:str,user=Depends(current_user)):
    from app.api.public import download_status as shared_status
    return shared_status(symbol)
@app.get('/scan')
def scan(user=Depends(current_user)):
    from app.services.multifactor import rated_many
    report=get('scan:latest',{})
    if report:
        from app.services.multifactor import rated_report
        report=rated_report(report,user)
    return report
@app.post('/line/webhook')
async def webhook(request:Request):
    body=await request.body()
    if not line.verify(body,request.headers.get('x-line-signature','')): raise HTTPException(401,'invalid signature')
    try: events=json.loads(body).get('events',[])
    except (ValueError,AttributeError): raise HTTPException(400,'invalid JSON')
    failed=False
    for event in events:
        is_follow=event.get('type')=='follow'
        if not is_follow and (event.get('type')!='message' or event.get('message',{}).get('type')!='text'): continue
        if event.get('source',{}).get('type')!='user': continue
        user=event['source'].get('userId')
        if not user:continue
        event_id=event.get('webhookEventId')
        if not event_id: continue
        key='event:'+event_id
        # 處理失敗釋放 claim；已成功回覆的事件忽略 redelivery。
        if not claim(key,{'status':'processing','at':time.time()}):
            state=get(key,{})
            if state.get('status')=='done': continue
            if time.time()-state.get('at',0)<60: failed=True; continue
        try:
            text=await asyncio.to_thread(commands.respond,user,'開始使用' if is_follow else event['message']['text'])
            await asyncio.to_thread(line.reply,event['replyToken'],text)
            put(key,{'status':'done','at':time.time()})
        except Exception:
            log.exception('webhook event failed')
            put(key,{'status':'retry','at':0}); failed=True
    if failed: raise HTTPException(503,'retry later')
    return {'ok':True}

@app.get('/strategy')
def strategy(user=Depends(current_user)):
    from app.services.multifactor import settings_for
    return settings_for(user)

@app.put('/strategy')
async def update_strategy(request:Request,user=Depends(current_user)):
    from app.services.multifactor import save_settings
    body=await limited_body(request,32768)
    try:return save_settings(user,json.loads(body))
    except (ValueError,TypeError,KeyError):raise HTTPException(400,'設定格式或門檻錯誤')

@app.post('/annual/{symbol}')
async def import_annual(symbol:str,request:Request,user=Depends(current_user)):
    from app.services.annual_data import import_csv
    body=await limited_body(request,131072)
    try:return import_csv(user,symbol,body.decode('utf-8-sig'))
    except (ValueError,UnicodeDecodeError) as exc:raise HTTPException(400,str(exc))

@app.get('/ratings')
def ratings(user=Depends(current_user)):
    from app.services.multifactor import rated_many
    from app.db import get_many
    from app.services.research import quotes_for
    return rated_many(quotes_for(watches(user)[:30]),user)

@app.get('/annual-supplement/{symbol}')
def annual_supplement_get(symbol:str,user=Depends(current_user)):
    from app.services.annual_data import supplemental_rows
    try:return supplemental_rows(user,symbol)
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.put('/ttm-eps/{symbol}')
async def ttm_eps_save(symbol:str,request:Request,user=Depends(current_user)):
    from app.services.annual_data import save_ttm_eps
    try:return save_ttm_eps(user,symbol,json.loads(await limited_body(request,4096)))
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))

@app.put('/ttm-eps-components/{symbol}')
async def ttm_components_save(symbol:str,request:Request,user=Depends(current_user)):
    from app.services.annual_data import save_ttm_components
    try:return save_ttm_components(user,symbol,json.loads(await limited_body(request,16384)))
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))

@app.patch('/annual-supplement/{symbol}')
async def annual_supplement_save(symbol:str,request:Request,user=Depends(current_user)):
    from app.services.annual_data import supplement
    body=await limited_body(request,32768)
    try:return supplement(user,symbol,json.loads(body))
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))

async def limited_body(request,limit):
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>limit:raise HTTPException(413,'內容超過大小限制')
        chunks.append(chunk)
    return b''.join(chunks)

@app.middleware('http')
async def private_response_headers(request,call_next):
    response=await call_next(request)
    if request.url.path.startswith('/auth'):
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
    return response

@app.get('/assistant/preferences')
def assistant_preferences(user=Depends(current_user)):
    from app.services.assistant import preferences
    return preferences(user)

@app.put('/assistant/preferences')
async def assistant_preferences_update(request:Request,user=Depends(current_user)):
    from app.services.assistant import save
    try:return save(user,json.loads(await limited_body(request,2048)))
    except (ValueError,TypeError):raise HTTPException(400,'助理設定格式錯誤')


@app.get('/recommendations/preferences')
def recommendations_preferences(user=Depends(current_user)):
    from app.services.market_recommendations import preferences
    return preferences(user)

@app.put('/recommendations/preferences')
def recommendations_preferences_update(body:Notice,user=Depends(current_user)):
    from app.services.market_recommendations import enable
    return enable(user,body.enabled)

@app.get('/recommendations/latest')
def recommendations_latest(user=Depends(current_user)):
    return get('recommendations:latest:'+user,{})

@app.get('/four-rankings/latest')
def four_rankings_latest(user=Depends(current_user)):
    from app.day_trader.reporting import latest
    return latest(user)

@app.get('/four-rankings/preferences')
def four_rankings_preferences(user=Depends(current_user)):
    from app.day_trader.reporting import preferences
    return preferences(user)

@app.put('/four-rankings/preferences')
def four_rankings_preferences_update(body:Notice,user=Depends(current_user)):
    from app.day_trader.reporting import set_enabled
    return set_enabled(user,body.enabled)


# V2.5: only the predesignated, authenticated LINE user may initialize.
# No endpoint exists to select/change the designated administrator.
class AdminOTP(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")

@app.get('/admin/bootstrap/status')
def admin_bootstrap_status(user=Depends(current_user)):
    """Return only the caller's own designation; do not disclose administrator identity."""
    from app.day_trader.admin_bootstrap import _record, _valid_line_id
    import hmac
    row = _record()
    designated = bool(row and _valid_line_id(user)
                      and hmac.compare_digest(row['user'], user)
                      and hmac.compare_digest(row['line_id'], user))
    return {'designated': designated, 'initialized': bool(row['initialized']) if designated else False}

@app.post('/admin/bootstrap/otp')
def admin_bootstrap_send_otp(user=Depends(current_user)):
    from app.day_trader.admin_bootstrap import issue_initialization_otp
    try:
        return issue_initialization_otp(user)
    except PermissionError:
        raise HTTPException(403, '無法發送初始化驗證碼')
    except Exception:
        log.exception('admin bootstrap LINE delivery failed')
        raise HTTPException(503, 'LINE 驗證碼暫時無法發送')

@app.post('/admin/bootstrap/verify')
def admin_bootstrap_verify(body: AdminOTP, user=Depends(current_user)):
    from app.day_trader.admin_bootstrap import verify_initialization_otp
    if not verify_initialization_otp(user, body.code):
        raise HTTPException(403, '驗證碼錯誤、過期或初始化不可用')
    return {'initialized': True}
