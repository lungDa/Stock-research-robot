"""Deterministic, explainable daily technical score. Completed bars only."""
from math import isfinite

def score(bars):
    """bars: oldest-first dicts with close, high, low, volume; at least 60 completed bars."""
    if not isinstance(bars,list) or len(bars)<60:
        return {"complete":False,"score":None,"reason":"至少需要60根已完成K棒"}
    for bar in bars:
        try:
            c,h,l,v=(float(bar[k]) for k in ("close","high","low","volume"))
        except (KeyError,TypeError,ValueError,OverflowError):
            return {"complete":False,"score":None,"reason":"OHLCV缺漏"}
        if not all(isfinite(x) for x in (c,h,l,v)) or c<=0 or l<=0 or h<max(c,l) or v<0:
            return {"complete":False,"score":None,"reason":"OHLCV數值無效"}
    close=[float(x["close"]) for x in bars]
    volume=[float(x["volume"]) for x in bars]
    if sum(volume[-21:-1])<=0:
        return {"complete":False,"score":None,"reason":"歷史成交量不足"}
    ma20=sum(close[-20:])/20
    ma60=sum(close[-60:])/60
    delta=[close[i]-close[i-1] for i in range(len(close)-14,len(close))]
    gain=sum(max(d,0) for d in delta)/14
    loss=sum(max(-d,0) for d in delta)/14
    rsi=100 if loss==0 and gain>0 else 50 if gain==loss==0 else 100-100/(1+gain/loss)
    vol_ratio=volume[-1]/(sum(volume[-21:-1])/20)
    # 40 points trend, 30 points momentum, 30 points volume.
    trend=(20 if close[-1]>ma20 else 0)+(20 if ma20>ma60 else 0)
    momentum=30 if 50<=rsi<=70 else 15 if 40<=rsi<50 or 70<rsi<=80 else 0
    vol=30 if vol_ratio>=1.5 and close[-1]>close[-2] else 15 if vol_ratio>=1 else 0
    result=trend+momentum+vol
    return {"complete":True,"score":result,"ma20":round(ma20,4),
            "ma60":round(ma60,4),"rsi14":round(rsi,2),
            "relative_volume":round(vol_ratio,3),
            "components":{"trend":trend,"momentum":momentum,"volume":vol},
            "note":"規則式研究評分；不是AI預測或交易指令"}
