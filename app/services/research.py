import time
from datetime import datetime,timezone
from app.db import get,put
from app.providers.market import normalize,fetch
from app.services.analysis import enrich

def research(symbol,refresh=False):
    symbol=normalize(symbol)
    cached=get('quote:'+symbol)
    if cached and not refresh and time.time()-cached['cached_at']<3600: return cached
    data=enrich(fetch(symbol))
    data['cached_at']=time.time()
    data['updated_at']=datetime.now(timezone.utc).isoformat()
    put('quote:'+symbol,data)
    return data

def cached_quote(symbol): return get('quote:'+normalize(symbol))
