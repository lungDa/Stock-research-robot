"""台股官方盤後資料。價格不還原，不依賴 Yahoo；缺資料不補造。"""
import json
import logging
import math
import re
import time
from contextvars import ContextVar
from datetime import date, datetime
from io import StringIO
from threading import Lock
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from app.db import get, put
from app.services.freshness import needs_evening_refresh

log = logging.getLogger(__name__)
_lock = Lock()
_last_request = {}
# 全市場輪掃只讀既有月快取；個股與自選追蹤才允許回補。
history_months = ContextVar("taiwan_history_months", default=1)
ALLOWED_HOSTS = {'openapi.twse.com.tw', 'www.twse.com.tw', 'isin.twse.com.tw', 'www.tpex.org.tw'}


_warning_until = {}
def warn_once(key, message):
    now = time.monotonic()
    if now >= _warning_until.get(key, 0):
        log.warning('%s（同類警告5分鐘內不重複）', message)
        _warning_until[key] = now + 300


def numeric(value):
    try:
        n = float(str(value).replace(',', '').strip())
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def trading_date(value):
    value = str(value).strip()
    parts = re.split(r'[/\-]', value)
    if len(parts) == 3:
        y, m, d = map(int, parts)
    elif value.isdigit() and len(value) in (7, 8):
        y, m, d = int(value[:-4]), int(value[-4:-2]), int(value[-2:])
    else:
        raise ValueError('官方資料日期格式無法辨識')
    if y < 1911:
        y += 1911
    return date(y, m, d).isoformat()


def _request(url, params=None):
    from app.providers.bounded_http import fetch_json
    host = urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        raise ValueError('非允許的官方來源')
    with _lock:
        delay = 3 - (time.monotonic() - _last_request.get(host, -10))
        if delay > 0: time.sleep(delay)
        _last_request[host] = time.monotonic()
    is_snapshot = 'STOCK_DAY_ALL' in url or 'daily_close_quotes' in url
    return fetch_json(url, params, max_bytes=1048576 if is_snapshot else 131072,
                      seconds=6, array=is_snapshot)


def cached(key, ttl, loader):
    key = 'official:' + key
    record = get(key)
    evening_refresh = False
    if record and key.startswith('official:snapshot:'):
        dates = [v.get('date','') for v in record['data'].values() if isinstance(v,dict) and 'date' in v]
        evening_refresh = needs_evening_refresh(record['at'], max(dates,default=''))
    if record and not evening_refresh and time.time() - record['at'] < ttl:
        return record['data']
    failure = get(key + ':failure', {})
    if time.time() < failure.get('until', 0):
        raise RuntimeError('官方來源冷卻中')
    try:
        data = loader()
        put(key, {'at': time.time(), 'data': data})
        return data
    except Exception:
        # 失敗也快取，避免掃描數百檔時重打整個市場端點。
        put(key + ':failure', {'until': time.time() + 300})
        raise


def _pick(row, *names):
    for name in names:
        if name in row and row[name] not in (None, ''):
            return row[name]
    return None


def snapshot(market):
    url = ('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL' if market == 'TW'
           else 'https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes')
    def load():
        payload = _request(url)
        complete = payload.get('complete', True) if isinstance(payload, dict) else True
        rows = payload.get('records', []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not rows:
            raise ValueError('官方每日行情格式異常或為空')
        out = {}
        for row in rows:
            code = str(_pick(row, 'Code', 'SecuritiesCompanyCode', 'CompanyCode', '代號', '證券代號') or '')
            close = numeric(_pick(row, 'ClosingPrice', 'Close', '收盤', '收盤價'))
            if not code or close is None or close <= 0:
                continue
            try:
                day = trading_date(_pick(row, 'Date', '日期', '資料日期'))
            except (ValueError, TypeError):
                continue
            out[code] = {'date': day, 'close': close,
                         'name': _pick(row, 'Name', 'CompanyName', 'SecuritiesCompanyName', '名稱', '證券名稱') or code}
        if not out:
            raise ValueError('官方每日行情沒有可解析的日期與收盤價')
        out['_meta'] = {'complete': complete}
        return out
    return cached('snapshot:' + market, 3600, load)


def catalog(market):
    # 商品分類屬後續完善項目；掃描不再下載龐大的ISIN HTML。
    record = get('official:catalog:' + market)
    if record:
        return record['data']
    return {}


def parse_month(payload, market):
    """用欄名比對；櫃買的成交仟股明確乘1000，不靠固定位置猜欄位。"""
    tables = payload.get('tables', [payload]) if isinstance(payload, dict) else []
    out = []
    for table in tables:
        fields = [re.sub(r'\s+', '', str(x)) for x in table.get('fields', [])]
        close_col = next((x for x in ('收盤價', '收盤') if x in fields), None)
        volume_col = next((x for x in ('成交股數', '成交仟股', '成交千股') if x in fields), None)
        if '日期' not in fields or close_col is None or volume_col is None:
            continue
        scale = 1000 if volume_col in ('成交仟股', '成交千股') else 1
        for raw in table.get('data', []):
            row = dict(zip(fields, raw))
            close = numeric(row.get(close_col))
            volume = numeric(row.get(volume_col))
            if close is None or close <= 0:
                continue
            try:
                day = trading_date(row['日期'])
            except (ValueError, TypeError):
                continue
            out.append({'date': day, 'close': close,
                        'volume': volume * scale if volume is not None and volume >= 0 else None})
    if not out:
        stat = str(payload.get('stat', '')) if isinstance(payload, dict) else ''
        if any(term in stat for term in ('沒有', '無資料', '很抱歉')):
            return []
        if isinstance(payload, dict) and any(t.get('fields') for t in tables):
            # 已識別的空表表示休市/新掛牌無交易；未知欄名則顯示格式異常。
            known = any('日期' in [re.sub(r'\s+', '', str(x)) for x in t.get('fields', [])] and
                        any('收盤' in str(x) for x in t.get('fields', [])) for t in tables)
            if known:
                return []
        raise ValueError('官方歷史資料欄位無法辨識')
    return out


def month(code, market, first, today):
    def load():
        if market == 'TW':
            payload = _request('https://www.twse.com.tw/exchangeReport/STOCK_DAY',
                               {'response': 'json', 'date': first.strftime('%Y%m%d'), 'stockNo': code})
        else:
            payload = _request('https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock',
                               {'response': 'json', 'date': first.strftime('%Y/%m/%d'), 'code': code})
        rows = parse_month(payload, market)
        if any(not r['date'].startswith(first.strftime('%Y-%m')) for r in rows):
            raise ValueError('官方回傳月份不符')
        return rows
    ttl = 3600 if first.year == today.year and first.month == today.month else 7 * 86400
    return cached(f'month:{market}:{code}:{first:%Y%m}', ttl, load)


def build_result(symbol, rows, meta, warnings):
    frame = pd.DataFrame(rows).sort_values('date').drop_duplicates('date', keep='last')
    close = frame['close']
    count = len(close)
    # 未還原價格若出現巨大跳空，禁止自動判定波段符合，避免拆併股假訊號。
    jump = bool((close.pct_change().abs() > .30).any())
    if jump:
        warnings.append('歷史價格出現超過30%跳動，可能涉及拆併股或其他事件；波段條件暫不判定。')
    if count < 60:
        warnings.append(f'目前僅取得{count}筆日線，未滿60筆的均線條件顯示缺資料。')
    volumes = frame['volume']
    volume_ok = count >= 20 and volumes.tail(20).notna().all() and volumes.tail(20).mean() > 0
    raw_volatility = float(close.pct_change().std() * 252 ** .5 * 100) if count >= 60 and not jump else None
    code, market = symbol.rsplit('.', 1)
    return {'symbol': symbol, 'name': meta.get('name') or code, 'kind': meta.get('kind', 'UNKNOWN'),
            'currency': '未確認（可能為外幣級別）' if code[-1:] in ('K', 'M', 'S', 'C') else 'TWD',
            'price': float(close.iloc[-1]), 'date': str(frame.iloc[-1]['date']),
            'ma20': float(close.tail(20).mean()) if count >= 20 and not jump else None,
            'ma60': float(close.tail(60).mean()) if count >= 60 and not jump else None,
            # 保留舊API欄名相容性，但price_basis明確揭露此處未還原。
            'adjusted_close': float(close.iloc[-1]),
            'volume_ratio': float(volumes.iloc[-1] / volumes.tail(20).mean()) if volume_ok else None,
            'volatility': raw_volatility, 'eps': None, 'roe': None, 'pe': None,
            'debt_to_equity': None, 'expense_ratio': None, 'yield': None,
            'history': [{'date': r['date'], 'close': float(r['close'])} for r in frame.to_dict('records')],
            'source': '臺灣證券交易所 TWSE' if market == 'TW' else '證券櫃檯買賣中心 TPEx',
            'price_basis': '未還原收盤價', 'history_count': count,
            'data_status': 'partial', 'warnings': list(dict.fromkeys(warnings))}


def fetch(symbol):
    """先取官方快照，最多新補1個月、讀取最近4個月快取；歷史失敗仍可顯示快照。"""
    if not re.fullmatch(r'\d{4,6}[A-Z]?\.(TW|TWO)', symbol):
        raise ValueError('台股代號格式錯誤；上櫃請加.TWO')
    code, market = symbol.rsplit('.', 1)
    today = datetime.now(ZoneInfo('Asia/Taipei')).date()
    started = time.monotonic()
    warnings = ['官方盤後日線非即時報價；價格未還原除權息，均線與波動僅供參考。',
                '此來源尚未整合EPS、ROE、ETF費用及近一年實際配息；存股缺項不會判定符合。']
    current = None
    try:
        quotes = snapshot(market)
        current = quotes.get(code)
        if not quotes.get('_meta', {}).get('complete', True):
            warnings.append('官方市場快照僅取得預算內的部分紀錄，不代表完整市場；仍以各筆實際日期為準。')
    except Exception:
        warn_once('snapshot:'+market, '官方快照暫不可用，使用可用快取或歷史資料')
        warnings.append('最新官方快照暫不可用；若歷史資料成功，將顯示其實際日期。')
    meta = {'name': current['name'] if current else code, 'kind': 'UNKNOWN'}
    try:
        meta.update(catalog(market).get(code, {}))
        if meta.get('kind') == 'UNKNOWN':
            warnings.append('商品分類尚未載入，目前顯示UNKNOWN。')
    except Exception:
        warn_once('catalog:'+market, '商品分類暫不可用，使用UNKNOWN')
        warnings.append('官方商品分類暫不可用，種類顯示UNKNOWN；不以代號猜測ETF。')
    rows = []
    first = today.replace(day=1)
    downloads_left = min(1, max(0, history_months.get()))
    for _ in range(4):
        if time.monotonic() - started > 12:
            warnings.append('歷史回補已達本次時間預算，先顯示已取得資料。')
            break
        try:
            record = get(f'official:month:{market}:{code}:{first:%Y%m}')
            ttl = 3600 if first.year == today.year and first.month == today.month else 7*86400
            if record and (time.time()-record['at'] < ttl or downloads_left == 0):
                rows.extend(record['data'])
            elif downloads_left > 0:
                downloads_left -= 1
                rows.extend(month(code, market, first, today))

        except Exception:
            warn_once('month:'+market, '官方月份暫不可用，停止本次回補')
            warnings.append('部分歷史月份暫不可用，已停止回補；不足的條件顯示缺資料。')
            break
        first = (pd.Timestamp(first) - pd.offsets.MonthBegin(1)).date()
    rows = [r for r in rows if r['date'] <= today.isoformat()]
    # 快照日期較新才附加；櫃買快照與月表成交量統計範圍不同，該點不混用量。
    missing_latest_history = bool(current and (not rows or current['date'] > max(r['date'] for r in rows)))
    if missing_latest_history and current['date'] <= today.isoformat():
        warnings.append('最新收盤價尚未併入完整月日線，波段條件暫不判定，避免跳過缺漏交易日。')
        rows.append({'date': current['date'], 'close': current['close'], 'volume': None})
    if not rows:
        raise RuntimeError(f'{symbol} 官方來源目前沒有可用日線，請確認代號/市場或稍後再試')
    result = build_result(symbol, rows, meta, warnings)
    if missing_latest_history:
        result['ma20'] = result['ma60'] = result['volume_ratio'] = None
    return result
