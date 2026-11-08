import time
import logging
from datetime import datetime,timezone
from app.db import get,put
from app.providers.market import normalize,fetch
from app.services.analysis import enrich
from app.services.freshness import needs_evening_refresh,local_now

def shared_us_quote(symbol):
    if symbol.endswith(('.TW','.TWO')):return None
    data=get('usdaily:quote:'+symbol)
    if not data:return None
    try:
        age=(local_now().date()-datetime.fromisoformat(data['date']).date()).days
        if not 0<=age<=7 or time.time()-data['cached_at']>72*3600:return None
    except (KeyError,ValueError,TypeError):return None
    return data

def annual_only(symbol):
    shared=get('annual:shared:'+symbol,{})
    if not shared.get('rows'):return None
    stock=any(r.get('provenance')=='SEC_10K' for r in shared['rows'].values())
    return enrich({'symbol':symbol,'name':symbol,'kind':'STOCK' if stock else 'UNKNOWN',
        'currency':'USD' if stock else '未提供','price':None,'date':'','history':[],
        **{k:None for k in ('ma20','ma60','adjusted_close','volume_ratio','volatility','eps','roe','pe','yield','expense_ratio')},
        'source':'年度財報共用快取','data_status':'fundamentals_only',
        'cached_at':time.time(),'updated_at':shared.get('updated_at'),
        'warnings':['行情暫不可用：僅顯示已下載的年度財報；價格、均線與動能缺資料。']})

def research(symbol,refresh=False):
    symbol=normalize(symbol)
    preferred=shared_us_quote(symbol)
    if preferred:return preferred
    cached=get('quote:'+symbol)
    if symbol.endswith(('.TW','.TWO')) and cached and cached.get('price_basis')!='未還原收盤價':
        cached=None
    ttl=1800 if cached and cached.get('price_basis')=='未還原收盤價' else (300 if cached and cached.get('data_status')=='partial' else 3600)
    evening_refresh=bool(cached and symbol.endswith(('.TW','.TWO')) and needs_evening_refresh(cached['cached_at'],cached.get('date')))
    if cached and not refresh and not evening_refresh and time.time()-cached['cached_at']<ttl:
        if symbol.endswith(('.TW','.TWO')):
            from app.providers.fundamentals import attach
            cached=enrich(attach(cached)); put('quote:'+symbol,cached)
        return cached
    try:
        data=fetch(symbol)
        if symbol.endswith(('.TW','.TWO')):
            from app.providers.fundamentals import attach
            data=attach(data)
        data=enrich(data)
    except Exception:
        # 保留原行情日期與快取時間，不把舊資料偽裝成新報價。
        if cached and cached.get('data_status')!='fundamentals_only' and time.time()-cached['cached_at']<=72*3600:
            logging.getLogger(__name__).warning('來源暫不可用，使用舊行情快取：%s',symbol)
            return {**cached,'data_status':'stale','warnings':list(cached.get('warnings',[]))+['來源更新失敗，目前顯示舊快取；請核對行情日期，勿視為最新報價。']}
        partial=annual_only(symbol)
        if partial:
            put('quote:'+symbol,partial)
            return partial
        raise
    data['cached_at']=time.time()
    data['updated_at']=datetime.now(timezone.utc).isoformat()
    put('quote:'+symbol,data)
    return data

def cached_quote(symbol):
    symbol=normalize(symbol)
    preferred=shared_us_quote(symbol)
    if preferred:return preferred
    data=get('quote:'+symbol)
    if data and symbol.endswith(('.TW','.TWO')):
        from app.providers.fundamentals import attach
        data=enrich(attach(data))
    return data
