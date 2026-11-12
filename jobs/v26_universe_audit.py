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
    """Official registries are the authoritative company universe.

    The legacy universe:small feed is not a complete ordinary-stock census.
    Accept only fresh official company registries with a fully attributable
    source and valid company codes; never fill unknowns from market quotes.
    """
    now = time.time()
    markets = {}
    issues = []
    all_symbols = []
    seen = set()
    counts = {}
    for market in ('TW', 'TWO'):
        record = get('official:catalog:' + market, {})
        source = ENDPOINTS[market]
        if not isinstance(record, dict):
            issues.append(market + ':官方名錄缺失')
            continue
        stamp = record.get('at')
        if (record.get('source') != source
                or record.get('scope') != 'OFFICIAL_COMPANY_REGISTRY'
                or type(stamp) not in (int, float)
                or not 0 <= now - stamp <= CLASSIFICATION_TTL):
            issues.append(market + ':官方名錄來源不符或已過期')
            continue
        data = record.get('data')
        if not isinstance(data, dict) or not data:
            issues.append(market + ':官方名錄為空')
            continue
        symbols = []
        for code, item in data.items():
            symbol = str(code) + '.' + market
            if (not SYMBOL.fullmatch(symbol) or
                    not isinstance(item, dict) or
                    item.get('kind') != 'STOCK' or
                    not isinstance(item.get('name'), str) or
                    not item['name'].strip() or
                    code in seen):
                issues.append(market + ':官方名錄包含無效或重複公司代號')
                continue
            seen.add(code)
            symbols.append(symbol)
        counts[market] = len(symbols)
        all_symbols.extend(symbols)
        markets[market] = {'at': stamp, 'source': source, 'count': len(symbols)}
    verified = not issues and len(markets) == 2 and bool(all_symbols)
    summary = {'at': now, 'verified': verified,
               'scope': 'TW_TWO_ORDINARY_STOCKS',
               'market_counts': counts, 'stock_count': len(all_symbols),
               'issues_count': len(issues), 'issue_samples': issues[:30],
               'catalogs': markets, 'method': 'OFFICIAL_COMPANY_REGISTRY'}
    put('v26:universe:verified_symbols',
        {'at': now, 'verified': verified,
         'symbols': sorted(all_symbols) if verified else [],
         'method': 'OFFICIAL_COMPANY_REGISTRY'})
    put('v26:universe:audit', summary)
    return summary


if __name__ == '__main__':
    print(run())
