"""Read-only audit for a targeted stock's annual paid-dividend cash-flow totals.

No new table, no external calls, and no implied zero for absent records.
"""
import re
from app.db import get_many

PREFIXES = ('cashflow:official:', 'annual:shared:', 'financial:official:')
STOCK = re.compile(r'^\d{4}\.(TW|TWO)$')


def audit(symbol, years, docs):
    if not STOCK.fullmatch(symbol):
        raise ValueError('invalid TW/TWO stock')
    result = []
    for year in years:
        if type(year) is not int or not 2013 <= year <= 2100:
            raise ValueError('invalid fiscal year')
        candidates = []
        for prefix in PREFIXES:
            row = ((docs.get(prefix + symbol) or {}).get('rows') or {}).get(str(year), {})
            if not isinstance(row, dict):
                continue
            value = row.get('cash_dividends_paid')
            meta = (row.get('field_sources') or {}).get('cash_dividends_paid') or {}
            if not isinstance(meta, dict):
                meta = {}
            source = meta.get('url') or row.get('source_url')
            unit = meta.get('unit')
            period_end = meta.get('period_end')
            valid = (type(value) in (int, float) and value >= 0
                     and __import__('math').isfinite(value)
                     and isinstance(source, str) and source.startswith('https://')
                     and unit == 'TWD' and period_end == f'{year}-12-31'
                     and bool(meta.get('basis')))
            candidates.append({'key': prefix + symbol, 'valid': valid,
                               'reason': 'validated' if valid else 'incomplete_provenance'})
        verified = [c for c in candidates if c['valid']]
        result.append({'year': year, 'status': 'present_verified' if verified else
                       'needs_provenance' if candidates else 'missing',
                       'sources': verified or candidates})
    return {'symbol': symbol, 'field': 'cash_dividends_paid',
            'years': result, 'missing_years': [r['year'] for r in result if r['status'] != 'present_verified'],
            'note': '只檢查已保存來源證明；不代表已核對原始財報內容'}


def read(symbol='2330.TW', years=(2021, 2022, 2023)):
    if not STOCK.fullmatch(symbol):
        raise ValueError('invalid TW/TWO stock')
    keys = [prefix + symbol for prefix in PREFIXES]
    return audit(symbol, years, get_many(keys))
