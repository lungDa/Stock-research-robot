import time
import logging
from datetime import datetime,timezone
from app.db import get,put
from app.providers.market import normalize,fetch
from app.services.analysis import enrich
from app.services.freshness import needs_evening_refresh,local_now,mark_cached,quote_due

def prefer_tw_backup(symbol,cached,read=get):
    from app.providers.tw_daily import shared
    backup=shared(symbol,read)
    if not backup:return cached
    if not cached or quote_due(cached) or backup['date']>cached.get('date','') or (
        backup['date']==cached.get('date') and cached.get('ma60') is None and backup.get('ma60') is not None):
        return backup
    return cached

def shared_us_quote(symbol):
    if symbol.endswith(('.TW','.TWO')):return None
    data=get('usdaily:quote:'+symbol)
    if not data:return None
    try:
        age=(local_now().date()-datetime.fromisoformat(data['date']).date()).days
        if not 0<=age<=7 or time.time()-data['cached_at']>36*3600:return None
    except (KeyError,ValueError,TypeError):return None
    return data

def annual_only(symbol):
    shared=get('annual:shared:'+symbol,{})
    eps=get('eps:official:'+symbol,{})
    financial=get('financial:official:'+symbol,{})
    if not shared.get('rows') and not eps.get('rows') and not financial.get('rows'):return None
    us=any(r.get('provenance')=='SEC_10K' for r in shared.get('rows',{}).values())
    stock=us or bool(eps.get('rows')) or bool(financial.get('rows'))
    return enrich({'symbol':symbol,'name':symbol,'kind':'STOCK' if stock else 'UNKNOWN',
        'currency':'USD' if us else 'TWD' if stock else '未提供','price':None,'date':'','history':[],
        **{k:None for k in ('ma20','ma60','adjusted_close','volume_ratio','volatility','eps','roe','pe','yield','expense_ratio')},
        'source':'年度財報共用快取','data_status':'fundamentals_only',
        'cached_at':time.time(),'updated_at':financial.get('updated_at') or shared.get('updated_at'),
        'warnings':['行情暫不可用：僅顯示已下載的年度財報；價格、均線與動能缺資料。']})

def research(symbol,refresh=False):
    symbol=normalize(symbol)
    preferred=shared_us_quote(symbol)
    if preferred:return preferred
    cached=get('quote:'+symbol)
    preferred_tw=prefer_tw_backup(symbol,cached)
    if preferred_tw is not cached:return preferred_tw
    if symbol.endswith(('.TW','.TWO')) and cached and cached.get('price_basis')!='未還原收盤價':
        cached=None
    if cached and not refresh and not quote_due(cached):
        if symbol.endswith(('.TW','.TWO')):
            from app.providers.fundamentals import attach
            from app.providers.taiwan_official import refresh_cached_history
            cached=enrich(attach(refresh_cached_history(cached))); put('quote:'+symbol,cached)
        return cached
    if cached and time.time()<get('quote_refresh:'+symbol,{}).get('next_attempt',0):
        return mark_cached(cached)
    try:
        data=fetch(symbol)
        if symbol.endswith(('.TW','.TWO')):
            from app.providers.fundamentals import attach
            data=attach(data)
        data=enrich(data)
    except Exception:
        put('quote_refresh:'+symbol,{'next_attempt':time.time()+300})
        # 保留原行情日期與快取時間，不把舊資料偽裝成新報價。
        if cached and cached.get('data_status')!='fundamentals_only' and time.time()-cached['cached_at']<=72*3600:
            logging.getLogger(__name__).warning('來源暫不可用，使用舊行情快取：%s',symbol)
            stale={**cached,'data_status':'stale','warnings':list(dict.fromkeys(cached.get('warnings',[])+['來源更新失敗，目前顯示舊快取；請核對行情日期，勿視為最新報價。']))}
            put('quote:'+symbol,stale)
            return stale
        partial=annual_only(symbol)
        if partial:
            put('quote:'+symbol,partial)
            return partial
        raise
    data['cached_at']=time.time()
    data['updated_at']=datetime.now(timezone.utc).isoformat()
    put('quote_refresh:'+symbol,{'next_attempt':0})
    put('quote:'+symbol,data)
    return mark_cached(data)


def quotes_for(symbols):
    from app.db import get_many
    keys=['quote:'+s for s in symbols]+['usdaily:quote:'+s for s in symbols if not s.endswith(('.TW','.TWO'))]
    keys += ['twdaily:quote:'+s for s in symbols if s.endswith(('.TW','.TWO'))]
    keys += ['annual:feed:'+s+':TaiwanStockPrice' for s in symbols if s.endswith(('.TW','.TWO'))]
    documents={}
    for offset in range(0,len(keys),80):documents.update(get_many(keys[offset:offset+80]))
    results=[]
    for symbol in symbols:
        quote=documents.get('quote:'+symbol)
        quote=prefer_tw_backup(symbol,quote,lambda k,d=None:documents.get(k,d))
        shared=documents.get('usdaily:quote:'+symbol)
        if shared:
            candidate=mark_cached(shared)
            if candidate.get('data_status')!='stale' and (not quote or shared.get('date','')>=quote.get('date','')):quote=shared
        if quote:results.append(mark_cached(quote))
    return results

def cached_quote(symbol):
    symbol=normalize(symbol)
    preferred=shared_us_quote(symbol)
    if preferred:return mark_cached(preferred)
    data=get('quote:'+symbol)
    data=prefer_tw_backup(symbol,data)
    if data and symbol.endswith(('.TW','.TWO')):
        from app.providers.fundamentals import attach
        from app.providers.taiwan_official import refresh_cached_history
        data=enrich(attach(refresh_cached_history(data)))
    return mark_cached(data)
