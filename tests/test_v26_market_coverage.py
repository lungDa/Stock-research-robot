from jobs.v26_market_coverage import inspect

def test_missing_never_counts_as_zero():
    years = [2025, 2024]
    docs = {'financial:official:2412.TW': {'rows': {'2025': {'eps': 3.1, 'roe_pct': 12.0}}},
            'cashflow:official:2412.TW': {'rows': {'2025': {'cash_dividends_paid': 0}}}}
    result = inspect('2412.TW', docs, years)
    assert result['known'] == 3
    assert result['expected'] == 6
    assert result['coverage'] == 0.5
    assert '2024:eps' in result['missing']

def test_nonfinite_is_missing():
    result = inspect('2412.TW', {'annual:shared:2412.TW': {'rows': {'2025': {'eps': float('nan')}}}}, [2025])
    assert result['known'] == 0
