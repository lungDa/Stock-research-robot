"""Regression checks for the V2.7 provisional six-factor backfill priority."""
from app.services.annual_priority import choose_market_batch
from app.services.data_queue import prioritize_missing
from jobs.v26_six_factor_coverage import inspect


def test_six_factor_missing_periods_are_counted_without_zero_filling():
    factors = {
        'eps': {'2025': {'value': 0, 'year': 2025,
                         'source_url': 'https://example.org/filing',
                         'unit': 'TWD/share', 'period_end': '2025-12-31'}}
    }
    result = inspect('2412.TW', factors, current_year=2026)
    assert result['expected_items'] == 31
    assert result['complete_items'] == 1
    assert result['missing_years']['eps'] == [2021, 2022, 2023, 2024]
    assert result['verified'] is False


def test_six_factor_priority_reserves_half_batch_for_market_rotation():
    universe = [f'{n:04d}.TW' for n in range(1000, 1020)]
    snapshot = {'at': 100, 'scope': 'SIX_FACTOR_PROVISIONAL',
                'symbols': universe[10:16]}
    selected, advanced = choose_market_batch(universe, 0, snapshot, now=100)
    assert selected == universe[10:16] + universe[:6]
    assert advanced == 6


def test_older_missing_stock_eventually_gets_priority():
    now = 30 * 86400
    candidates = [
        {'symbol': '1111.TW', 'missing_fields': 25, 'requested_at': 0},
        {'symbol': '2222.TW', 'missing_fields': 2, 'requested_at': now},
    ]
    ordered = prioritize_missing(candidates, now=now, starvation_days=3)
    assert ordered[0]['symbol'] == '2222.TW'
    # After enough time, an old request is no longer penalized by all gaps.
    later = prioritize_missing(candidates, now=now + 80 * 86400, starvation_days=3)
    assert later[0]['symbol'] == '1111.TW'
