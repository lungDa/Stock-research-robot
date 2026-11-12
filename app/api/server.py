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
from app.api.v26_coverage import router as coverage_router
app.include_router(coverage_router)

# Persisted maintenance flag survives Render restarts. The middleware runs
# before authentication, public routes, webhook handlers and background tasks.
# Fail closed if the flag cannot be read: do not accidentally admit writes.
@app.middleware('http')
async def maintenance_gate(request:Request,call_next):
    from fastapi.responses import JSONResponse
    path=request.url.path
    if path in ('/health','/ready','/maintenance/status','/admin/maintenance'):
        return await call_next(request)
    try:
        active=bool(get('system:maintenance',{}).get('enabled',False))
    except Exception:
        log.exception('maintenance state unavailable')
        return JSONResponse(status_code=503,content={'detail':'系統狀態暫不可確認，請稍後再試'})
    if active:
        return JSONResponse(status_code=503,content={'detail':'系統維護中，請稍後再試'},
                            headers={'Retry-After':'300','Cache-Control':'no-store'})
    return await call_next(request)

@app.get('/maintenance/status')
def maintenance_status():
    try:
        return {'maintenance':bool(get('system:maintenance',{}).get('enabled',False))}
    except Exception:
        return {'maintenance':True}

class MaintenanceSwitch(BaseModel):
    enabled:bool

@app.put('/admin/maintenance')
def set_maintenance(body:MaintenanceSwitch,user=Depends(current_admin)):
    # Authenticated administrator can also disable maintenance after validation.
    put('system:maintenance',{'enabled':body.enabled,'updated_at':time.time(),'by':user})
    return {'maintenance':body.enabled}
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


# V2.5 sensitive-operation authorization: intentionally separate from initial admin OTP.
# Call admin_stepup.require(request, scope) in every future sensitive write endpoint.
class AdminStepUpRequest(BaseModel):
    scope: str = Field(max_length=40)

class AdminStepUpVerify(AdminStepUpRequest):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")

@app.post('/admin/stepup/otp')
def admin_stepup_issue(body:AdminStepUpRequest, request:Request):
    from app.day_trader.admin_stepup import issue
    try:
        return issue(request, body.scope)
    except HTTPException:
        raise
    except Exception:
        log.exception('admin step-up delivery failed')
        raise HTTPException(503, '管理員驗證碼暫時無法發送')

@app.post('/admin/stepup/verify')
def admin_stepup_verify(body:AdminStepUpVerify, request:Request):
    from app.day_trader.admin_stepup import verify
    return verify(request, body.scope, body.code)

@app.get('/admin/stepup/status')
def admin_stepup_status(request:Request):
    from app.day_trader.admin_stepup import _identity, _key
    user, sid, session = _identity(request)
    state = get(_key(sid), {})
    remaining = min(state.get('grant_expires', 0), session['expires']) - time.time()
    return {'authorized': remaining > 0 and state.get('user') == user,
            'scope': state.get('scope') if remaining > 0 and state.get('user') == user else None,
            'expires_in': max(0, int(remaining))}


# V2.5 privileged AI quota management. Every mutation enforces the server-side
# device-bound LINE step-up grant; Streamlit visibility alone is never authority.
class AdminAILimitUpdate(BaseModel):
    normal_daily_limit: int = Field(ge=0, le=100000, strict=True)
    emergency_daily_limit: int = Field(ge=0, le=100000, strict=True)

@app.put('/admin/ai-limits/{target_user}')
def admin_ai_limits_update(target_user:str, body:AdminAILimitUpdate, request:Request):
    from app.day_trader.admin_stepup import require
    require(request, 'ai_limits')
    from app.day_trader.access_models import UserAILimit
    from app.db import Session
    from app.day_trader.admin_bootstrap import _valid_line_id
    if not _valid_line_id(target_user):
        raise HTTPException(400, 'LINE 使用者識別格式錯誤')
    with Session.begin() as session:
        record=session.get(UserAILimit, target_user)
        if record is None:
            record=UserAILimit(user=target_user)
            session.add(record)
        record.normal_daily_limit=body.normal_daily_limit
        record.emergency_daily_limit=body.emergency_daily_limit
    return {'user':target_user,'normal_daily_limit':body.normal_daily_limit,
            'emergency_daily_limit':body.emergency_daily_limit}

@app.get('/admin/ai-limits/{target_user}')
def admin_ai_limits_read(target_user:str, request:Request):
    from app.day_trader.admin_stepup import _identity
    _identity(request)
    from app.day_trader.access_models import UserAILimit
    from app.db import Session
    from app.day_trader.admin_bootstrap import _valid_line_id
    if not _valid_line_id(target_user):raise HTTPException(400, 'LINE 使用者識別格式錯誤')
    with Session() as session:
        row=session.get(UserAILimit,target_user)
        return {'user':target_user,'normal_daily_limit':row.normal_daily_limit if row else 0,
                'emergency_daily_limit':row.emergency_daily_limit if row else 0}


# Single-superadministrator policy: administrator designation is immutable through
# public APIs. Sensitive security actions require a device-bound LINE step-up.
@app.get('/admin/role-policy')
def admin_role_policy(request:Request):
    from app.day_trader.admin_stepup import _identity
    _identity(request)
    return {'mode':'single_superadmin','delegation_enabled':False,
            'administrator_transfer_enabled':False}

@app.post('/admin/security/revoke-other-devices')
def admin_security_revoke_other_devices(request:Request):
    from app.day_trader.admin_stepup import require, _identity
    from app.api.device_sessions import revoke_others
    require(request,'security_settings')
    user,sid,_=_identity(request)
    revoked=revoke_others(user,sid)
    return {'ok':True,'revoked':revoked}

@app.put('/admin/roles/{target_user}')
def admin_role_mutation_denied(target_user:str, request:Request):
    from app.day_trader.admin_stepup import require
    require(request,'role_management')
    raise HTTPException(403,'單一最高管理員模式不允許指派或轉移管理員權限')


@app.get('/ai/usage')
def personal_ai_usage(user=Depends(current_user)):
    from app.day_trader.ai_usage import usage
    return {'normal':usage(user),'emergency':usage(user,'emergency')}

@app.get('/admin/ai-usage/{target_user}')
def admin_ai_usage(target_user:str,request:Request):
    from app.day_trader.admin_stepup import _identity
    from app.day_trader.admin_bootstrap import _valid_line_id
    from app.day_trader.ai_usage import usage
    _identity(request)
    if not _valid_line_id(target_user):raise HTTPException(400,'LINE 使用者識別格式錯誤')
    return {'user':target_user,'normal':usage(target_user),
            'emergency':usage(target_user,'emergency')}


# Explicit AI commentary endpoint. Quantitative quote endpoints remain free of AI quota.
class AIReviewRequest(BaseModel):
    symbol: str = Field(min_length=1,max_length=25)
    kind: str = Field(default="normal",pattern="^(normal|emergency)$")

@app.post('/ai/review')
async def ai_review(body:AIReviewRequest,user=Depends(current_user)):
    from app.providers.market import normalize
    from app.services.research import cached_quote
    from app.services.multifactor import rated
    from app.day_trader.metered_ai import metered_review
    try:
        symbol=normalize(body.symbol)
        quote=await asyncio.to_thread(cached_quote,symbol)
        if not quote or quote.get("data_status") in ("stale","fundamentals_only"):
            raise HTTPException(409,"缺少有效行情資料，請先更新行情；不扣除 AI 額度")
        rated_quote=await asyncio.to_thread(rated,quote,user)
        grade=(rated_quote.get("rating") or {}).get("grade")
        rating=rated_quote.get("rating") or {}
        checks=rating.get("checks") or []
        # Send only finite, verified factor values; never fabricate missing data.
        factors=[{"metric":c.get("metric"),"value":c.get("value"),
                  "passed":c.get("passed"),"threshold":c.get("threshold")}
                 for c in checks[:24] if c.get("value") is not None]
        report={"symbol":symbol,"signal":grade or "資料不足",
                "fundamental_score":rating.get("score"),
                "technical":{"price":rated_quote.get("price"),
                             "date":rated_quote.get("date"),
                             "ma20":rated_quote.get("ma20"),
                             "ma60":rated_quote.get("ma60")},
                "factors":factors,"coverage":rating.get("coverage"),
                "data_status":rated_quote.get("data_status")}
        return await asyncio.to_thread(metered_review,user,report,kind=body.kind,enabled=True)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
