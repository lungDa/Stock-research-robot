"""Taiwan daily backup from the same FinMind source; no network in readers."""
from datetime import timedelta,datetime,timezone
from app.providers.annual_free import finite,valid_day
from app.providers.taiwan_official import build_result
from app.services.freshness import local_now,market_usable


def parse(symbol,records,today,at,previous=None):
    previous=previous or {};code=symbol.split('.')[0];clean={}
    for row in records:
        day=valid_day(row.get('date'));price=finite(row.get('close'))
        if str(row.get('stock_id'))!=code or not day or day>today or day<today-timedelta(days=160) or price is None or price<=0:continue
        volume=finite(row.get('Trading_Volume'))
        if volume is not None and volume<0:volume=None
        item={'date':str(day),'close':price,'volume':volume}
        if str(day) in clean and clean[str(day)]!=item:raise ValueError('Conflicting Taiwan daily records')
        clean[str(day)]=item
    if not clean:raise ValueError('No verified Taiwan daily records')
    result=build_result(symbol,list(clean.values()),previous,[
        'FinMind台股備援盤後日線；價格未還原除權息，非即時報價。'])
    result.update(source='FinMind / TaiwanStockPrice',cached_at=at,
                  updated_at=datetime.fromtimestamp(at,timezone.utc).isoformat())
    return result


def shared(symbol,read):
    if not symbol.endswith(('.TW','.TWO')):return None
    import time
    state=read('twdaily:quote:'+symbol)
    choices=[]
    if state and 0<=time.time()-state.get('cached_at',0)<=36*3600 and market_usable(state):choices.append(state)
    feed=read('annual:feed:'+symbol+':TaiwanStockPrice',{})
    at=feed.get('at',0)
    if 0<=time.time()-at<=36*3600:
        try:
            result=parse(symbol,feed.get('records',[]),local_now().date(),at,read('quote:'+symbol,{}))
            if market_usable(result):choices.append(result)
        except ValueError:pass
    return max(choices,key=lambda d:(d['date'],d['cached_at'])) if choices else None
