"""FinMind US daily data, downloaded by worker only; UI reads shared cache."""
import math
from datetime import date,datetime,timezone
import pandas as pd
from app.providers.annual_free import finite,valid_day
from app.services.analysis import enrich


def parse(symbol,records,today,previous=None):
    clean={}
    for r in records:
        d=valid_day(r.get('date')); close=finite(r.get('Close',r.get('close')))
        if str(r.get('stock_id'))!=symbol or not d or d>today or not close or close<=0:continue
        adj=finite(r.get('Adj_Close',r.get('adj_close')))
        volume=finite(r.get('Volume',r.get('volume')))
        if adj is not None and adj<=0:adj=None
        clean[str(d)]=(close,adj,volume if volume is not None and volume>=0 else None)
    if len(clean)<60:raise ValueError('US daily history needs 60 valid sessions')
    days=sorted(clean)[-270:]
    if (today-date.fromisoformat(days[-1])).days>7:raise ValueError('US daily source is stale')
    values=[clean[d] for d in days];has_adjustment=all(v[1] is not None for v in values)
    adjusted=pd.Series([v[1] for v in values],dtype=float) if has_adjustment else None
    volumes=[v[2] for v in values[-20:]]
    volume_ratio=volumes[-1]/(sum(volumes)/20) if len(volumes)==20 and all(v is not None for v in volumes) and sum(volumes)>0 else None
    # Explicit provider classification only. A bare symbol is not enough to infer ETF/stock.
    previous=previous or {}
    kind=previous.get('kind','UNKNOWN')
    return enrich({'symbol':symbol,'name':previous.get('name',symbol),'kind':kind,'currency':'USD',
        'price':values[-1][0],'date':days[-1],'adjusted_close':values[-1][1] if has_adjustment else None,
        'ma20':float(adjusted.tail(20).mean()) if has_adjustment else None,
        'ma60':float(adjusted.tail(60).mean()) if has_adjustment else None,
        'volatility':float(adjusted.pct_change().std()*252**.5*100) if has_adjustment else None,
        'volume_ratio':volume_ratio,'eps':None,'roe':None,'pe':None,'debt_to_equity':None,
        'yield':None,'expense_ratio':None,
        'history':[{'date':d,'close':clean[d][0]} for d in days],
        'source':'FinMind / USStockPrice','price_basis':'未還原收盤價；技術條件僅使用來源Adj_Close',
        'data_status':'partial','updated_at':datetime.now(timezone.utc).isoformat(),
        'warnings':['美股盤後日線，非即時報價；配息、費用率與財報另依來源判定。']+
            ([] if has_adjustment else ['來源缺還原價格，本次不計算均線與波動，避免拆股除息扭曲。'])})
