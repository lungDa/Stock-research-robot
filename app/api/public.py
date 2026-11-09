"""免登入公開行情與預設選股；不提供個人清單、設定、年報匯入或通知操作。"""
import asyncio,time
from fastapi import APIRouter,HTTPException
from app.db import get,claim
from app.services.freshness import local_now
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
            if data:
                if time.time()-data.get('cached_at',0)>36*3600:
                    data={**data,'data_status':'stale','warnings':list(data.get('warnings',[]))+['公開模式顯示較舊快取，請核對實際行情日。']}
            else:
                if not await asyncio.to_thread(reserve_refresh):raise HTTPException(429,'公開查詢更新額度已用完，請稍後重試或LINE登入使用個人查詢')
                data=await asyncio.to_thread(research,symbol)
        return await asyncio.to_thread(rated,data,'public')
    except ValueError as e:raise HTTPException(400,str(e))
    except HTTPException:raise
    except Exception:raise HTTPException(503,'行情暫不可用，請稍後再試')

@router.get('/scan')
def scan():
    report=get('scan:latest',{})
    if report:report['ratings']=rated_many(report.get('candidates',[])[:30],'public')
    return report

@router.post('/fundamentals/prepare/{symbol}')
async def prepare_fundamentals(symbol:str):
    from app.services.query_fundamentals import prepare
    try:
        async with lock:return await asyncio.to_thread(prepare,symbol)
    except ValueError as exc:raise HTTPException(400,str(exc))
