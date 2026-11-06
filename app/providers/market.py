"""Yahoo 資料轉接：不把供應商物件傳到介面層。"""
import math, re, time
import pandas as pd
import yfinance as yf

def normalize(value):
    value=value.strip().upper()
    if value.isdigit(): value += '.TW'  # 上櫃請明確用 .TWO
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-^=]{0,24}',value):
        raise ValueError('代號格式錯誤；例如 2330、6488.TWO、AAPL')
    return value

def number(value):
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError): return None

def dividend_yield(dividends,price,now=None):
    if not price or dividends.empty: return None
    now=pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
    if now.tzinfo is None: now=now.tz_localize('UTC')
    idx=pd.to_datetime(dividends.index,utc=True)
    return float(dividends[(idx>now-pd.Timedelta(days=365)) & (idx<=now)].sum()/price*100)

def fetch(symbol):
    last=None
    for attempt in range(3):
        try:
            ticker=yf.Ticker(normalize(symbol))
            hist=ticker.history(period='1y',auto_adjust=False,timeout=15)
            hist=hist.dropna(subset=['Close'])
            if len(hist)<60: raise ValueError('有效日線不足60筆')
            # 技術分析採還原收盤價，避免拆股/除息直接扭曲均線。
            close=hist['Adj Close'] if 'Adj Close' in hist else hist['Close']
            info=ticker.info or {}
            price=float(hist.Close.iloc[-1])
            return {'symbol':normalize(symbol),'name':info.get('shortName',symbol),
                'kind':'ETF' if info.get('quoteType')=='ETF' else ('STOCK' if info.get('quoteType')=='EQUITY' else 'UNKNOWN'),
                'currency':info.get('currency'),'price':price,'date':str(hist.index[-1].date()),
                'ma20':float(close.tail(20).mean()),'ma60':float(close.tail(60).mean()),
                'adjusted_close':float(close.iloc[-1]),
                'volume_ratio':number(hist.Volume.iloc[-1]/hist.Volume.tail(20).mean()) if hist.Volume.tail(20).mean()>0 else None,
                'volatility':number(close.pct_change().std()*252**.5*100),
                'eps':number(info.get('trailingEps')),'roe':number(info.get('returnOnEquity')),
                'pe':number(info.get('trailingPE')),'debt_to_equity':number(info.get('debtToEquity')),
                'expense_ratio':number(info.get('annualReportExpenseRatio')),
                'yield':dividend_yield(hist.loc[hist['Dividends']>0,'Dividends'],price) if 'Dividends' in hist else None,
                'history':[{'date':str(i.date()),'close':float(v)} for i,v in hist.Close.items()],
                'source':'Yahoo Finance / yfinance'}
        except Exception as exc:
            last=exc
            if attempt<2: time.sleep(2**attempt)
    raise RuntimeError(f'{symbol} 行情取得失敗') from last
