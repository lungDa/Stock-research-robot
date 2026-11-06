import asyncio,json,logging,time
from fastapi import FastAPI,Depends,HTTPException,Request
from pydantic import BaseModel,Field
from app.db import init_db,get,claim,put
from app.api.security import current_user
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
    yield
app=FastAPI(title='股海燈塔 API',lifespan=lifespan)
# 單一程序限制同時向行情商發出請求；免費部署維持一個 worker。
quote_lock=asyncio.Semaphore(1)
class Symbol(BaseModel): symbol:str=Field(max_length=25)
class Notice(BaseModel): enabled:bool
@app.get('/health')
def health(): return {'status':'ok'}
@app.get('/me')
def me(user=Depends(current_user)): return {'user':user}
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
    toggle(user,body.enabled); return {'ok':True}
@app.get('/quote/{symbol}')
async def quote(symbol:str,user=Depends(current_user)):
    try:
        async with quote_lock: return await asyncio.to_thread(research,symbol)
    except ValueError as e: raise HTTPException(400,str(e))
    except Exception:
        log.exception('quote failed'); raise HTTPException(503,'行情暫不可用，請稍後再試')
@app.get('/scan')
def scan(user=Depends(current_user)): return get('scan:latest',{})
@app.post('/line/webhook')
async def webhook(request:Request):
    body=await request.body()
    if not line.verify(body,request.headers.get('x-line-signature','')): raise HTTPException(401,'invalid signature')
    try: events=json.loads(body).get('events',[])
    except (ValueError,AttributeError): raise HTTPException(400,'invalid JSON')
    failed=False
    for event in events:
        if event.get('type')!='message' or event.get('message',{}).get('type')!='text': continue
        if event.get('source',{}).get('type')!='user': continue
        user=event['source'].get('userId')
        if user not in settings.users.values(): continue
        event_id=event.get('webhookEventId')
        if not event_id: continue
        key='event:'+event_id
        # 處理失敗釋放 claim；已成功回覆的事件忽略 redelivery。
        if not claim(key,{'status':'processing','at':time.time()}):
            state=get(key,{})
            if state.get('status')=='done': continue
            if time.time()-state.get('at',0)<60: failed=True; continue
        try:
            try: text=await asyncio.to_thread(commands.handle,user,event['message']['text'])
            except ValueError as e: text=str(e)
            await asyncio.to_thread(line.reply,event['replyToken'],text)
            put(key,{'status':'done','at':time.time()})
        except Exception:
            log.exception('webhook event failed')
            put(key,{'status':'retry','at':0}); failed=True
    if failed: raise HTTPException(503,'retry later')
    return {'ok':True}
