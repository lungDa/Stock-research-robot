"""免登入公開行情與預設選股；不提供個人清單、設定、年報匯入或通知操作。"""
import asyncio,time
from fastapi import APIRouter,HTTPException,BackgroundTasks
from app.db import get,claim
from app.services.freshness import local_now,quote_due,mark_cached
from app.services.research import cached_quote,research
from app.services.multifactor import rated,rated_many
from app.providers.market import normalize
router=APIRouter(prefix='/public')
from app.api.limits import quote_lock as lock

def reserve_refresh():
    minute=str(int(time.time()//60));day=local_now().date().isoformat()
    if not any(claim('public:minute:'+minute+':'+str(i),{'at':time.time()}) for i in range(2)):return False
    return any(claim('public:day:'+day+':'+str(i),{'at':time.time()}) for i in range(20))

@router.get('/quote/{symbol}')
async def quote(symbol:str):
    try:
        symbol=normalize(symbol)
        async with lock:
            data=await asyncio.to_thread(cached_quote,symbol)
            if quote_due(data):
                if await asyncio.to_thread(reserve_refresh):
                    data=await asyncio.to_thread(research,symbol)
                elif data:
                    data={**mark_cached(data),'refresh_deferred':True,
                          'warnings':list(dict.fromkeys(data.get('warnings',[])+['公開更新額度已滿，本次保留既有行情；請核對行情日。']))}
                else:
                    raise HTTPException(429,'公開查詢更新額度已用完，請稍後重試或LINE登入使用個人查詢')
        return await asyncio.to_thread(rated,data,'public')
    except ValueError as e:raise HTTPException(400,str(e))
    except HTTPException:raise
    except Exception:raise HTTPException(503,'行情暫不可用，請稍後再試')

@router.get('/scan')
def scan():
    report=get('scan:latest',{})
    if report:
        from app.services.multifactor import rated_report
        report=rated_report(report,'public')
    return report

@router.post('/fundamentals/prepare/{symbol}')
async def prepare_fundamentals(symbol:str):
    from app.services.query_fundamentals import prepare
    try:
        async with lock:return await asyncio.to_thread(prepare,symbol)
    except ValueError as exc:raise HTTPException(400,str(exc))


@router.post('/fundamentals/request/{symbol}')
def request_fundamentals(symbol:str,background_tasks:BackgroundTasks):
    from app.services.query_fundamentals import request_download,process_download
    try:
        result=request_download(symbol)
        if result.get('state')=='queued':background_tasks.add_task(process_download,result['symbol'])
        return result
    except ValueError as exc:raise HTTPException(400,str(exc))


@router.get('/fundamentals/status/{symbol}')
def download_status(symbol:str):
    from app.services.query_fundamentals import status
    try:return status(symbol)
    except ValueError as exc:raise HTTPException(400,str(exc))
