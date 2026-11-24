import pandas as pd
import pytest

from app.services.defensive_model import (
    BENCHMARK_WEIGHTS, RiskRule, align_released_returns, backtest, downside_statistics, rank_candidates, risk_level,
)


def test_us_close_uses_next_taiwan_session_across_dst_and_holiday():
    opens = pd.DatetimeIndex(['2025-03-07 09:00', '2025-03-11 09:00',
                              '2025-03-12 09:00'], tz='Asia/Taipei')
    releases = pd.Series([-.10, .10, -.04], index=pd.DatetimeIndex(
        ['2025-03-07 16:00', '2025-03-10 16:00', '2025-03-11 16:00'], tz='America/New_York'))
    aligned = align_released_returns(releases, opens)
    assert pd.isna(aligned.iloc[0])
    assert aligned.iloc[1] == pytest.approx(-.01)
    assert aligned.iloc[2] == pytest.approx(-.04)


def test_level_selects_highest_trigger_and_marks_missing_benchmarks():
    rules = [RiskRule(drop, drop, 2, drop) for drop in (.01, .02, .03, .04)]
    values = dict.fromkeys(BENCHMARK_WEIGHTS, 0)
    values['sox'] = -.031
    assert risk_level(values, rules) == 3
    del values['sox']
    assert risk_level(values, rules) is None


def test_downside_statistics_cannot_read_after_cutoff():
    dates = pd.date_range('2025-01-01', periods=4, tz='UTC')
    market = pd.Series([-.02, -.01, .01, -.20], index=dates)
    result = downside_statistics(-market, market, dates[2], 1, severe_drop=.015, min_pairs=3)
    assert result['pairs'] == 3
    assert result['pearson'] == pytest.approx(-1)
    assert result['spearman'] == pytest.approx(-1)
    assert result['downside_beta'] == pytest.approx(-1)
    assert result['up_probability'] == 1
    assert result['severe_market_mean'] == .02


def test_backtest_executes_at_following_open_and_excludes_unfinished_trades():
    dates = pd.bdate_range('2025-01-01 09:00', periods=25, tz='Asia/Taipei', normalize=False)
    prices = pd.Series(range(100, 125), index=dates)
    signal = {'action': 'buy', 'level': 3, 'benchmark': 'sox'}
    report = backtest(prices, {dates[0]: signal, dates[2]: signal, dates[20]: signal}, dates[-1], 1, 10)
    assert report['summary']['count'] == 1
    assert report['trades'][0]['entry'] == dates[1].isoformat()
    assert report['trades'][0]['exit'] == dates[11].isoformat()
    assert report['levels'][3]['mean_return'] == pytest.approx(111 / 101 - 1)
    assert report['benchmarks']['sox']['count'] == 1


def test_rankings_relax_only_empty_tiers_and_exclude_unavailable_scores():
    candidates = [
        {'symbol': 'A', 'eligible': True, 'scores': dict.fromkeys(BENCHMARK_WEIGHTS, .95)},
        {'symbol': 'B', 'eligible': True, 'scores': dict.fromkeys(BENCHMARK_WEIGHTS, .70)},
        {'symbol': 'C', 'eligible': True, 'scores': {'sox': 1}},
        {'symbol': 'D', 'eligible': False, 'scores': dict.fromkeys(BENCHMARK_WEIGHTS, 1)},
    ]
    rankings = rank_candidates(candidates, [.99, .90, .60])
    assert rankings['combined']['relaxation_tier'] == 1
    assert [item['symbol'] for item in rankings['combined']['items']] == ['A']
    assert rankings['sox']['relaxation_tier'] == 0
    assert [item['symbol'] for item in rankings['sox']['items']] == ['C']


def test_adjusted_returns_never_bridge_a_missing_session():
    from app.services.defensive_model import adjusted_stock_returns

    sessions = pd.date_range('2025-01-06 13:30', periods=4, tz='Asia/Taipei')
    history = {'rows': [
        {'date': '2025-01-06', 'close': 100},
        {'date': '2025-01-08', 'close': 110},
        {'date': '2025-01-09', 'close': 121},
    ]}
    result = adjusted_stock_returns(history, sessions)
    assert result.iloc[:3].isna().all()
    assert result.iloc[3] == pytest.approx(.10)
