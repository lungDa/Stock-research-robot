"""V2.6 ordinary-stock universe audit; fail closed on unknown product types.

Do not infer a complete ordinary-stock universe from a source's 'complete'
flag alone. Classification must be independently supported for every row.
"""
import re
import time

MAX_AGE_SECONDS = 8 * 86400
from app.db import get, get_many, init_db, put
from jobs.v26_official_catalog import ENDPOINTS
CLASSIFICATION_TTL = 8 * 86400

SYMBOL = re.compile(r'^\d{4}\.(TW|TWO)$')


def audit(markets, quotes, now=None, official_codes=None):
    now = time.time() if now is None else now
    issues = []
    included = {}
    seen_codes = {}
    counts = {'TW': 0, 'TWO': 0}
    excluded = {'ETF': 0, 'OTHER': 0, 'UNKNOWN': 0}
    check_official = official_codes is not None
    official_codes = official_codes or {}
    for market in ('TW', 'TWO'):
        state = markets.get(market, {})
        if state.get('complete') is not True or not state.get('rows'):
            issues.append(market + ':母體來源未確認完整')
        stamp = state.get('at')
        if type(stamp) not in (int, float) or not 0 <= now - stamp <= MAX_AGE_SECONDS:
            issues.append(market + ':母體來源過期或缺少時間戳記')
        if check_official and market not in official_codes:
            issues.append(market + ':缺少官方公司名錄，無法核對數量')
        for row in state.get('rows', []):
            if not isinstance(row, dict):
                issues.append(market + ':無效列')
                continue
            symbol = str(row.get('symbol', ''))
            if not SYMBOL.fullmatch(symbol) or not symbol.endswith('.' + market):
                issues.append(market + ':非四碼普通股候選或市場別不一致:' + symbol)
                continue
            code = symbol.split('.')[0]
            if code in seen_codes and seen_codes[code] != market:
                issues.append(code + ':跨市場重複代號')
            seen_codes[code] = market
            classification = quotes.get(symbol, {})
            kind = classification.get('kind', 'UNKNOWN')
            stamp = classification.get('classification_at')
            if kind == 'STOCK' and (type(stamp) not in (int, float) or not 0 <= now - stamp <= CLASSIFICATION_TTL or not classification.get('classification_source')):
                kind = 'UNKNOWN'
            if kind == 'STOCK':
                if symbol in included:
                    issues.append(symbol + ':重複代號')
                else:
                    included[symbol] = row
                    counts[market] += 1
            else:
                excluded[kind if kind in ('ETF', 'OTHER') else 'UNKNOWN'] += 1
                if kind not in ('ETF', 'OTHER'):
                    issues.append(symbol + ':尚未確認商品分類')
    for market, codes in official_codes.items():
        actual = {symbol.split('.')[0] for symbol in included if symbol.endswith('.' + market)}
        missing = set(codes) - actual
        extra = actual - set(codes)
        if missing:
            issues.append(market + ':官方公司名錄缺漏' + str(len(missing)) + '檔')
        if extra:
            issues.append(market + ':不在官方公司名錄' + str(len(extra)) + '檔')
    return {'verified': not issues and bool(included),
            'scope': 'TW_TWO_ORDINARY_STOCKS', 'market_counts': counts,
            'excluded': excluded, 'stock_count': len(included),
            'issues_count': len(issues), 'issue_samples': issues[:30],
            'symbols': sorted(included)}


def invalidate_snapshot(reason):
    put('v26:universe:verified_symbols', {'at': time.time(), 'verified': False, 'symbols': [], 'reason': str(reason)[:200]})


def run():
    init_db()
    try:
        return _run_audit()
    except Exception as exc:
        invalidate_snapshot(type(exc).__name__)
        raise


def _run_audit():
    markets = {m: get('universe:small:' + m, {}) for m in ('TW', 'TWO')}
    candidates = sorted({row.get('symbol') for state in markets.values()
                         for row in state.get('rows', [])
                         if isinstance(row, dict) and SYMBOL.fullmatch(str(row.get('symbol', '')))})
    quotes = {}
    for start in range(0, len(candidates), 80):
        keys = ['quote:' + symbol for symbol in candidates[start:start + 80]]
        docs = get_many(keys)
        quotes.update({symbol: docs.get('quote:' + symbol, {}) for symbol in candidates[start:start + 80]})
    official_codes = {}
    for market in ('TW', 'TWO'):
        record = get('official:catalog:' + market, {})
        if not isinstance(record, dict):
            continue
        at, source = record.get('at'), record.get('source')
        if (type(at) not in (int, float) or not 0 <= time.time() - at <= CLASSIFICATION_TTL
                or source != ENDPOINTS[market] or record.get('scope') != 'OFFICIAL_COMPANY_REGISTRY'):
            continue
        data = record.get('data', {})
        if not isinstance(data, dict):
            continue
        official_codes[market] = set(data)
        for code, item in data.items():
            symbol = str(code) + '.' + market
            if symbol in quotes and isinstance(item, dict) and item.get('kind') in ('STOCK', 'ETF', 'OTHER'):
                quotes[symbol] = {'kind': item['kind'], 'classification_at': at, 'classification_source': source}
    result = audit(markets, quotes, official_codes=official_codes)
    summary = {k: v for k, v in result.items() if k != 'symbols'}
    summary['at'] = time.time()
    # A complete market source alone is insufficient evidence of stock kind.
    put('v26:universe:verified_symbols', {'at': summary['at'],
        'verified': result['verified'],
        'symbols': result['symbols'] if result['verified'] else []})
    put('v26:universe:audit', summary)
    return summary


if __name__ == '__main__':
    print(run())
