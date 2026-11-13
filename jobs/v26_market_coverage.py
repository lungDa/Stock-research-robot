"""Conservative, resumable V2.6 market data coverage and priority snapshot.

Coverage here is a *diagnostic* for three annual source fields, NOT the
six-factor verified completeness required to activate the 95% night gate.
"""
import math
import re
import time
from app.db import get, get_many, put, init_db
from app.services.freshness import local_now
from app.services.data_queue import prioritize_missing
from app.services.v26_coverage_adapter import from_documents, PREFIXES

FIELDS = ('eps', 'roe_pct', 'cash_dividends_paid')


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def inspect(symbol, docs, years):
    annual = docs.get('financial:official:' + symbol, {}).get('rows', {})
    shared = docs.get('annual:shared:' + symbol, {}).get('rows', {})
    eps = docs.get('eps:official:' + symbol, {}).get('rows', {})
    cash = docs.get('cashflow:official:' + symbol, {}).get('rows', {})
    found = 0
    missing = []
    for year in years:
        key = str(year)
        for field in FIELDS:
            sources = (annual.get(key, {}), shared.get(key, {}))
            if field == 'eps':
                sources += (eps.get(key, {}),)
            if field == 'cash_dividends_paid':
                sources += (cash.get(key, {}),)
            if any(number(row.get(field)) for row in sources if isinstance(row, dict)):
                found += 1
            else:
                missing.append(f'{year}:{field}')
    return {'known': found, 'expected': len(years) * len(FIELDS),
            'coverage': round(found / (len(years) * len(FIELDS)), 4),
            'missing': missing}


def run():
    init_db()
    now = time.time()
    years = list(range(local_now().year - 1, local_now().year - 6, -1))
    markets = [get('universe:small:' + market, {}) for market in ('TW', 'TWO')]
    complete = all(m.get('complete') is True and m.get('rows') for m in markets)
    symbols = sorted({row.get('symbol') for m in markets for row in m.get('rows', [])
                      if isinstance(row, dict) and re.fullmatch(r'\d{4}\.(TW|TWO)', str(row.get('symbol', '')))})
    if not symbols:
        return {'state': 'no_universe', 'verified': False}
    total_known = 0
    six_known = 0
    six_expected = 0
    six_missing = {}
    priority = []
    completed_symbols = []
    previous = get('v26:priority:partial', {})
    previous_waiting = previous.get('waiting_since', {}) if isinstance(previous, dict) else {}
    if not isinstance(previous_waiting, dict):
        previous_waiting = {}
    for offset in range(0, len(symbols), 20):
        batch = symbols[offset:offset + 20]
        keys = [f'{prefix}{symbol}' for symbol in batch for prefix in
                ('financial:official:', 'annual:shared:', 'eps:official:',
                 'cashflow:official:', 'quote:')]
        docs = {}
        for i in range(0, len(keys), 80):
            docs.update(get_many(keys[i:i + 80]))
        for symbol in batch:
            quote = docs.get('quote:' + symbol, {})
            if quote.get('kind') == 'ETF':
                continue
            six = from_documents(symbol, docs, current_year=local_now().year)
            six_known += six['complete_items']
            six_expected += six['expected_items']
            for field, gaps in six['missing_years'].items():
                six_missing[field] = six_missing.get(field, 0) + len(gaps)
            status = inspect(symbol, docs, years)
            total_known += status['known']
            # A partial EPS/ROE history is useful for prioritization, but is
            # not proof that a stock meets the user's multi-factor criteria.
            if not status['missing']:
                completed_symbols.append(symbol)
            else:
                priority.append({'symbol': symbol,
                                 'missing_fields': len(status['missing']),
                                 'requested_at': previous_waiting.get(symbol, now)})
    priority = prioritize_missing(priority, now=now)
    count = len(priority) + len(completed_symbols)
    summary = {'state': 'diagnostic', 'at': now, 'market_complete': complete,
               'market_symbols': count, 'years': years, 'fields': list(FIELDS),
               'known_fields': total_known, 'expected_fields': count * 15,
               'partial_coverage_ratio': round(total_known / (count * 15), 4) if count else 0,
               'verified': False,
               'note': '僅EPS/ROE/現金股利支出三欄診斷；不含FCF、營收CAGR、殖利率與十年配息，不能觸發95%切換'}
    put('v26:coverage:diagnostic', summary)
    put('v27:coverage:six_factor_provisional', {
        'at': now, 'scope': 'SIX_FACTOR_PROVISIONAL', 'verified': False,
        'market_complete': complete, 'stock_count': count,
        'known_items': six_known, 'expected_items': six_expected,
        'coverage_ratio': round(six_known / six_expected, 4) if six_expected else 0,
        'missing_by_factor': six_missing,
        'note': '六項指標既有資料初步診斷；未完成官方來源交叉核對，不能用於95%切換。',
    })
    # Keep a bounded snapshot. The worker rotates through this list and its
    # own checkpoint; this is not yet the full six-factor priority engine.
    put('v26:priority:partial', {'at': now,
                                  'symbols': [row['symbol'] for row in priority] + sorted(completed_symbols),
                                  'waiting_since': {row['symbol']: row['requested_at'] for row in priority},
                                  'scope': 'THREE_FIELD_DIAGNOSTIC'})
    return summary


if __name__ == '__main__':
    print(run())
