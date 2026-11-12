"""Conservative six-factor adapter over existing Neon document keys.

This is a per-stock diagnostic, not a verified all-market completeness audit.
Missing provenance or period metadata stays missing; no synthetic values.
"""
import re
import math
from datetime import date
from app.db import get_many
from jobs.v26_six_factor_coverage import inspect

PREFIXES = ('financial:official:', 'annual:shared:', 'eps:official:',
            'cashflow:official:')
FIELDS = ('eps', 'roe_pct', 'fcf', 'revenue_cagr',
          'cash_yield_pct', 'cash_dividend_years')
CODE = re.compile(r'^\d{4}\.(TW|TWO)$')


def _source(row, field):
    sources = row.get('field_sources') or {}
    meta = sources.get(field) if isinstance(sources, dict) else {}
    return meta if isinstance(meta, dict) else {}


def _derived_fcf(row, year):
    """Only derive annual FCF when OCF and capex have matching proven periods."""
    fields = ('operating_cash_flow', 'capital_expenditure')
    metas = [_source(row, f) for f in fields]
    for field, meta in zip(fields, metas):
        value = row.get(field)
        if type(value) not in (int, float) or not math.isfinite(value):
            return None
        if not meta.get('url') or not meta.get('unit'):
            return None
        if meta.get('period_end') != f'{year}-12-31':
            return None
    if metas[0]['unit'] != metas[1]['unit'] or row['capital_expenditure'] < 0:
        return None
    return {'value': row['operating_cash_flow'] - row['capital_expenditure'],
            'year': year, 'source_url': metas[0]['url'],
            'unit': metas[0]['unit'], 'period_end': f'{year}-12-31',
            'cashflow_basis': 'annual_ocf_minus_positive_capex'}


def _record(row, field, year):
    if not isinstance(row, dict):
        return None
    if field == 'fcf' and row.get('fcf') is None:
        return _derived_fcf(row, year)
    value = row.get(field)
    meta = _source(row, field)
    source_url = meta.get('url') or row.get('source_url')
    unit = meta.get('unit') or row.get('unit')
    if not source_url or not unit or type(value) not in (int, float) or not math.isfinite(value):
        return None
    record = {'value': value, 'year': year, 'source_url': source_url,
              'unit': unit, 'period_end': meta.get('period_end') or row.get('period_end')}
    if field == 'fcf':
        record['cashflow_basis'] = meta.get('cashflow_basis') or row.get('cashflow_basis')
    if field == 'cash_yield_pct':
        record.update(price_date=meta.get('price_date') or row.get('price_date'),
                      dividend_basis=meta.get('dividend_basis') or row.get('dividend_basis'),
                      price_source=meta.get('price_source') or row.get('price_source'))
    return record


def from_documents(symbol, documents, current_year=None):
    if not CODE.fullmatch(symbol):
        raise ValueError('限四碼台灣上市上櫃股票')
    current_year = date.today().year if current_year is None else current_year
    factors = {field: {} for field in FIELDS}
    for prefix in PREFIXES:
        rows = (documents.get(prefix + symbol) or {}).get('rows') or {}
        if not isinstance(rows, dict):
            continue
        for year_key, row in rows.items():
            if not str(year_key).isdigit():
                continue
            year = int(year_key)
            for field in FIELDS:
                if str(year) in factors[field]:
                    continue
                record = _record(row, field, year)
                if record is not None:
                    from jobs.v26_six_factor_coverage import valid_record
                    if valid_record(record, year, field):
                        factors[field][str(year)] = record
    result = inspect(symbol, factors, current_year=current_year)
    result['verified'] = False  # No full cross-source audit or company-period proof yet.
    result['status'] = 'provisional'
    result['source'] = 'NEON_EXISTING_DOCUMENTS'
    result['note'] = '既有 Neon 欄位初步比對；尚未核對全市場及來源報表，不得作為95%切換依據'
    return result


def read_stock(symbol):
    if not CODE.fullmatch(symbol):
        raise ValueError('限四碼台灣上市上櫃股票')
    keys = [prefix + symbol for prefix in PREFIXES]
    return from_documents(symbol, get_many(keys))
