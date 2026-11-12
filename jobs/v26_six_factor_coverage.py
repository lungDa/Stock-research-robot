"""V2.6.2 six-factor completeness, independent of financial *performance*.

Only period-identified, attributable observations count. Missing and zero are
different. Never activate a 95% scheduling gate from this module alone.
"""
from datetime import date
from math import isfinite

FACTORS = ('eps', 'roe_pct', 'fcf', 'revenue_cagr', 'cash_yield_pct',
           'cash_dividend_years')
HISTORY_YEARS = 5
DIVIDEND_YEARS = 10


def valid_number(value):
    return type(value) in (int, float) and isfinite(value)


def valid_record(record, year, field):
    if not isinstance(record, dict) or not valid_number(record.get('value')):
        return False
    if not record.get('source_url') or record.get('year') != year:
        return False
    if field == 'cash_yield_pct':
        return bool(record.get('price_date') and record.get('dividend_basis')
                    and record.get('price_source'))
    if field == 'fcf':
        return bool(record.get('cashflow_basis') and record.get('unit'))
    return bool(record.get('unit') and record.get('period_end') == f'{year}-12-31')


def inspect(symbol, factors, current_year=None):
    """factors: field -> year -> standardized record; no guessed fallbacks."""
    current_year = date.today().year if current_year is None else current_year
    years = range(current_year - HISTORY_YEARS, current_year)
    dividend_years = range(current_year - DIVIDEND_YEARS, current_year)
    requirements = {
        'eps': years, 'roe_pct': years, 'fcf': years,
        'revenue_cagr': (current_year - 1,),
        'cash_yield_pct': years, 'cash_dividend_years': dividend_years,
    }
    missing = {}
    available = 0
    expected = 0
    for field, periods in requirements.items():
        records = factors.get(field, {})
        missing[field] = []
        for year in periods:
            expected += 1
            if valid_record(records.get(str(year)), year, field):
                available += 1
            else:
                missing[field].append(year)
    return {'symbol': symbol, 'verified': available == expected,
            'complete_items': available, 'expected_items': expected,
            'coverage_ratio': round(available / expected, 4),
            'missing_years': missing,
            'factor_complete': {field: not gaps for field, gaps in missing.items()},
            'scope': 'SIX_FACTOR_PERIOD_VERIFIED',
            'note': '僅計算已核對期間與來源的資料覆蓋率；不代表符合投資條件'}


def market_summary(results, universe_verified):
    """The scheduler may only consider a trusted universe and complete audits."""
    rows = list(results)
    eligible = bool(universe_verified) and bool(rows) and all(
        row.get('scope') == 'SIX_FACTOR_PERIOD_VERIFIED' for row in rows)
    complete = sum(row.get('verified') is True for row in rows)
    return {'verified': eligible, 'stock_count': len(rows),
            'fully_complete_stocks': complete,
            'complete_stock_ratio': round(complete / len(rows), 4) if rows else 0,
            'gate_eligible': False,  # Requires verified universe identity, snapshot age and exact stock-set reconciliation.
            'note': '尚須檢查母體快照有效期、全數股票處理完成及資料來源新鮮度'}
