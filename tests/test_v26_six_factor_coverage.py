from jobs.v26_six_factor_coverage import inspect, market_summary


def record(year, field):
    value = {'value': 0.0, 'year': year, 'source_url': 'https://example.org/source',
             'unit': 'TWD', 'period_end': f'{year}-12-31'}
    if field == 'cash_yield_pct':
        value.update(price_date=f'{year}-12-31', dividend_basis='paid',
                     price_source='https://example.org/price')
    if field == 'fcf':
        value['cashflow_basis'] = 'operating_cashflow_minus_capex'
    return value


def filled():
    fields = {}
    for field in ('eps', 'roe_pct', 'fcf', 'cash_yield_pct'):
        fields[field] = {str(y): record(y, field) for y in range(2021, 2026)}
    fields['revenue_cagr'] = {'2025': record(2025, 'revenue_cagr')}
    fields['cash_dividend_years'] = {str(y): record(y, 'cash_dividend_years')
                                     for y in range(2016, 2026)}
    return fields


def test_complete_six_factor_zero_is_valid():
    result = inspect('2330.TW', filled(), current_year=2026)
    assert result['verified'] and result['coverage_ratio'] == 1


def test_missing_dividend_year_blocks_complete():
    fields = filled()
    del fields['cash_dividend_years']['2016']
    result = inspect('2330.TW', fields, current_year=2026)
    assert not result['verified']
    assert result['missing_years']['cash_dividend_years'] == [2016]


def test_unattributed_or_wrong_period_not_counted():
    fields = filled()
    fields['eps']['2025']['source_url'] = ''
    fields['fcf']['2024']['year'] = 2023
    assert inspect('2330.TW', fields, current_year=2026)['complete_items'] == 29


def test_gate_needs_verified_universe():
    full = inspect('2330.TW', filled(), current_year=2026)
    assert not market_summary([full], universe_verified=False)['gate_eligible']
    assert market_summary([full], universe_verified=True)['gate_eligible']
    assert not market_summary([], universe_verified=True)['gate_eligible']
