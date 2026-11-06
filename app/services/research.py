import time
import logging
from datetime import datetime,timezone
from app.db import get,put
from app.providers.market import normalize,fetch
from app.services.analysis import enrich

def research(symbol,refresh=False):
    symbol=normalize(symbol)
    cached=get('quote:'+symbol)
    if symbol.endswith(('.TW','.TWO')) and cached and cached.get('price_basis')!='未還原收盤價':
        cached=None
    ttl=1800 if cached and cached.get('price_basis')=='未還原收盤價' else (300 if cached and cached.get('data_status')=='partial' else 3600)
    if cached and not refresh and time.time()-cached['cached_at']<ttl: return cached
    try:
        data=enrich(fetch(symbol))
    except Exception:
        # 保留原行情日期與快取時間，不把舊資料偽裝成新報價。
        if cached and time.time()-cached['cached_at']<=72*3600:
            logging.getLogger(__name__).warning('使用舊行情快取：%s',symbol,exc_info=True)
            return {**cached,'data_status':'stale','warnings':list(cached.get('warnings',[]))+['來源更新失敗，目前顯示舊快取；請核對行情日期，勿視為最新報價。']}
        raise
    data['cached_at']=time.time()
    data['updated_at']=datetime.now(timezone.utc).isoformat()
    put('quote:'+symbol,data)
    return data

def cached_quote(symbol): return get('quote:'+normalize(symbol))
