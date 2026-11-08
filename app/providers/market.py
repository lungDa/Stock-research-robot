"""Yahoo 資料轉接：不把供應商物件傳到介面層。"""
import math, re, time
import logging
from threading import Lock
from yfinance.exceptions import YFRateLimitError
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

# 程序內冷卻：遵守限流，不更換IP或繞過限制。
log=logging.getLogger(__name__)
_state_lock=Lock()
_cooldowns={'history':0.0,'info':0.0}

def _cooling(endpoint):
    with _state_lock: return time.monotonic()<_cooldowns[endpoint]

def _pause(endpoint,seconds):
    with _state_lock:
        _cooldowns[endpoint]=max(_cooldowns[endpoint],time.monotonic()+seconds)

def _optional_info(ticker):
    if _cooling('info'):
        return {}, ['Yahoo基本資料冷卻中；本次僅使用日線，存股資料尚不完整。']
    try:
        info=ticker.info or {}
        if not isinstance(info,dict) or not info:
            return {}, ['Yahoo未提供基本資料；本次僅使用日線，存股資料尚不完整。']
        return info, []
    except YFRateLimitError:
        _pause('info',300)
        log.warning('Yahoo基本資料限流，暫停基本資料請求5分鐘')
        return {}, ['Yahoo基本資料限流；保留價格、圖表與波段條件，缺少的財務資料不參與存股判定。']
    except Exception:
        _pause('info',60)
        log.warning('Yahoo基本資料暫不可用',exc_info=True)
        return {}, ['Yahoo基本資料暫不可用；保留日線分析，缺少的財務資料不參與存股判定。']

def _history(symbol):
    if _cooling('history'):
        raise RuntimeError('Yahoo行情仍在限流冷卻中，請稍後再試')
    last=None
    for attempt in range(3):
        try:
            ticker=yf.Ticker(symbol)
            hist=ticker.history(period='1y',auto_adjust=False,timeout=15)
            if hist.empty or 'Close' not in hist: raise ValueError('沒有取得有效日線')
            hist=hist.dropna(subset=['Close'])
            if len(hist)<60: raise ValueError('有效日線不足60筆')
            return ticker,hist
        except YFRateLimitError as exc:
            _pause('history',300)
            raise RuntimeError('Yahoo行情來源限流，已暫停行情請求5分鐘') from exc
        except ValueError: raise
        except Exception as exc:
            last=exc
            if attempt<2: time.sleep(2**attempt)
    raise RuntimeError(f'{symbol} 行情取得失敗') from last

def fetch(symbol):
    symbol=normalize(symbol)
    if symbol.endswith(('.TW', '.TWO')):
        from app.providers.taiwan_official import fetch as fetch_official
        return fetch_official(symbol)
    ticker,hist=_history(symbol)
    # 技術分析採還原收盤價，避免拆股/除息直接扭曲均線。
    close=hist['Adj Close'] if 'Adj Close' in hist else hist['Close']
    info, warnings = _optional_info(ticker)
    price=float(hist.Close.iloc[-1])
    return {'symbol':normalize(symbol),'name':info.get('shortName',symbol),
        'kind':'ETF' if info.get('quoteType')=='ETF' else ('STOCK' if info.get('quoteType')=='EQUITY' else 'UNKNOWN'),
        'currency':info.get('currency') or ('TWD' if symbol.endswith(('.TW','.TWO')) else '未提供'),'price':price,'date':str(hist.index[-1].date()),
        'ma20':float(close.tail(20).mean()),'ma60':float(close.tail(60).mean()),
        'adjusted_close':float(close.iloc[-1]),
        'volume_ratio':number(hist.Volume.iloc[-1]/hist.Volume.tail(20).mean()) if hist.Volume.tail(20).mean()>0 else None,
        'volatility':number(close.pct_change().std()*252**.5*100),
        'eps':number(info.get('trailingEps')),'roe':number(info.get('returnOnEquity')),
        'pe':number(info.get('trailingPE')),'debt_to_equity':number(info.get('debtToEquity')),
        'expense_ratio':number(info.get('annualReportExpenseRatio')),
        'yield':dividend_yield(hist.loc[hist['Dividends']>0,'Dividends'],price) if 'Dividends' in hist else None,
        'yield_basis':'trailing_paid_365d' if 'Dividends' in hist and (pd.Timestamp.now(tz='UTC')-pd.to_datetime(hist.index[0],utc=True)).days>=360 else None,
        'history':[{'date':str(i.date()),'close':float(v)} for i,v in hist.Close.items()],
        'source':'Yahoo Finance / yfinance', 'warnings':warnings,
        'data_status':'partial' if warnings else 'available'}
