"""Point-in-time calculations for downside research on verified price series."""
from dataclasses import dataclass
from math import isfinite

import pandas as pd


BENCHMARK_WEIGHTS = {
    'tw_electronics': .30,
    'tw_semiconductors': .25,
    '2330.TW': .20,
    'nasdaq_100': .10,
    'sox': .15,
}
LOOKBACK_YEARS = (1, 3, 5)
HOLDING_SESSIONS = (10, 20, 30)


@dataclass(frozen=True)
class RiskRule:
    single_drop: float
    multi_drop: float
    declining_count: int
    weighted_drop: float


def risk_level(returns, rules, weights=None):
    """Each rule corresponds to one ascending level and supports three trigger paths."""
    weights = BENCHMARK_WEIGHTS if weights is None else weights
    if set(weights) != set(BENCHMARK_WEIGHTS) or not all(
        isfinite(value) and value >= 0 for value in weights.values()
    ) or sum(weights.values()) <= 0:
        raise ValueError('invalid benchmark weights')
    if len(rules) != 4 or any(
        not 1 <= rule.declining_count <= len(weights)
        or any(not isfinite(value) or value <= 0 for value in
               (rule.single_drop, rule.multi_drop, rule.weighted_drop))
        for rule in rules
    ):
        raise ValueError('four valid risk rules are required')
    if any(key not in returns or not isfinite(returns[key]) for key in weights):
        return None
    weighted = sum(returns[key] * weight for key, weight in weights.items()) / sum(weights.values())
    return max((level for level, rule in enumerate(rules, start=1) if
                min(returns[key] for key in weights) <= -rule.single_drop
                or sum(returns[key] <= -rule.multi_drop for key in weights) >= rule.declining_count
                or weighted <= -rule.weighted_drop), default=0)


def align_released_returns(released, taiwan_opens):
    """Assign each release once, to the first verified Taiwan open strictly after release.

    Inputs use timezone-aware indexes. The Taiwan calendar supplies actual opens.
    Multiple US closes during Taiwan holidays compound into one observable return.
    A Taiwan session without a fresh release remains missing.
    """
    if (released.index.tz is None or taiwan_opens.tz is None
            or not taiwan_opens.is_monotonic_increasing
            or not taiwan_opens.is_unique or not released.index.is_unique
            or released.index.hasnans or taiwan_opens.hasnans):
        raise ValueError('valid unique timezone-aware releases and Taiwan opens are required')
    if any(not isfinite(value) or value < -1 for value in released):
        raise ValueError('invalid released return')
    positions = taiwan_opens.searchsorted(released.index, side='right')
    covered = positions < len(taiwan_opens)
    # The first open has no preceding calendar boundary in this input.
    covered &= positions > 0
    groups = (1 + released[covered]).groupby(positions[covered]).prod() - 1
    result = pd.Series(index=taiwan_opens, dtype=float)
    result.iloc[groups.index.to_numpy(dtype=int)] = groups.to_numpy()
    return result


def downside_statistics(stock_returns, benchmark_returns, as_of, years, *, severe_drop, min_pairs=60):
    if years not in LOOKBACK_YEARS or not isfinite(severe_drop) or severe_drop <= 0:
        raise ValueError('invalid research window or severe-drop threshold')
    if not stock_returns.index.is_unique or not benchmark_returns.index.is_unique:
        raise ValueError('return timestamps must be unique')
    start = as_of - pd.DateOffset(years=years)
    paired = pd.concat([stock_returns.rename('stock'), benchmark_returns.rename('benchmark')], axis=1)
    paired = paired.loc[(paired.index > start) & (paired.index <= as_of)].dropna()
    paired = paired.loc[paired.apply(lambda column: column.map(isfinite)).all(axis=1)]
    down = paired.loc[paired.benchmark < 0]
    severe = down.loc[down.benchmark <= -severe_drop]
    result = {'pairs': len(paired), 'down_sessions': len(down), 'severe_sessions': len(severe)}
    if len(paired) < min_pairs:
        return {**result, 'status': 'insufficient_data'}
    variance = down.benchmark.var()
    return {
        **result,
        'status': 'available',
        'pearson': _finite_or_none(paired.stock.corr(paired.benchmark)),
        'spearman': _finite_or_none(paired.stock.rank().corr(paired.benchmark.rank())),
        'up_probability': _finite_or_none((down.stock > 0).mean()),
        'down_market_mean': _finite_or_none(down.stock.mean()),
        'severe_market_mean': _finite_or_none(severe.stock.mean()),
        'downside_beta': _finite_or_none(down.stock.cov(down.benchmark) / variance) if variance > 0 else None,
    }


def _finite_or_none(value):
    return float(value) if isfinite(value) else None


def backtest(adjusted_opens, signals, as_of, years, holding_sessions):
    """Enter at the next session open and avoid overlapping trades in one symbol.

    Signals are indexed by the time they became available and contain their
    historical risk level and benchmark. Series must be from verified sources.
    """
    if years not in LOOKBACK_YEARS or holding_sessions not in HOLDING_SESSIONS:
        raise ValueError('unsupported backtest window')
    if (adjusted_opens.index.tz is None or not adjusted_opens.index.is_unique
            or not adjusted_opens.index.is_monotonic_increasing
            or any(not isfinite(price) or price <= 0 for price in adjusted_opens)):
        raise ValueError('verified adjusted session opens are required')
    prices = adjusted_opens.loc[adjusted_opens.index <= as_of]
    start = as_of - pd.DateOffset(years=years)
    trades = []
    last_exit = -1
    for available_at, signal in sorted(signals.items()):
        if not start <= available_at <= as_of or signal['action'] != 'buy':
            continue
        entry = prices.index.searchsorted(available_at, side='right')
        exit_ = entry + holding_sessions
        if entry <= last_exit or exit_ >= len(prices):
            continue
        trades.append({
            'entry': prices.index[entry].isoformat(), 'exit': prices.index[exit_].isoformat(),
            'return': float(prices.iloc[exit_] / prices.iloc[entry] - 1),
            'holding_sessions': holding_sessions, 'level': signal['level'],
            'benchmark': signal['benchmark'],
        })
        last_exit = exit_
    return {
        'trades': trades,
        'summary': _performance(trades),
        'levels': {level: _performance([trade for trade in trades if trade['level'] == level])
                   for level in range(5)},
        'benchmarks': {key: _performance([trade for trade in trades if trade['benchmark'] == key])
                       for key in BENCHMARK_WEIGHTS},
        'limitations': ['未計入交易稅、手續費、滑價與流動性限制', '績效以單一標的依序成交計算'],
    }


def _performance(trades):
    if not trades:
        return {'count': 0, 'win_rate': None, 'mean_return': None,
                'cumulative_return': None, 'mean_holding_sessions': None}
    returns = pd.Series([trade['return'] for trade in trades])
    return {
        'count': len(trades),
        'win_rate': float((returns > 0).mean()),
        'mean_return': float(returns.mean()),
        'cumulative_return': float((1 + returns).prod() - 1),
        'mean_holding_sessions': sum(trade['holding_sessions'] for trade in trades) / len(trades),
    }


def rank_candidates(candidates, thresholds, weights=None):
    """Rank verified, comparable 0–1 scores for the five benchmarks.

    Thresholds are ordered from strict to relaxed. Missing scores stay excluded
    in every tier. Technical and fundamental eligibility belongs to the caller.
    """
    weights = BENCHMARK_WEIGHTS if weights is None else weights
    if (set(weights) != set(BENCHMARK_WEIGHTS) or not all(
            isfinite(weight) and weight >= 0 for weight in weights.values())
            or sum(weights.values()) <= 0):
        raise ValueError('invalid benchmark weights')
    thresholds = tuple(thresholds)
    if (not thresholds or any(not isfinite(value) or not 0 <= value <= 1 for value in thresholds)
            or any(current < following for current, following in zip(thresholds, thresholds[1:]))):
        raise ValueError('provide thresholds in descending order')
    scores = {key: [] for key in ('combined', *BENCHMARK_WEIGHTS)}
    if len({candidate['symbol'] for candidate in candidates}) != len(candidates):
        raise ValueError('duplicate candidate symbols')
    denominator = sum(weights.values())
    for candidate in candidates:
        if candidate.get('eligible') is not True:
            continue
        row = candidate['scores']
        valid = {key: row[key] for key in BENCHMARK_WEIGHTS
                 if row.get(key) is not None and isfinite(row[key]) and 0 <= row[key] <= 1}
        for key, score in valid.items():
            scores[key].append({'symbol': candidate['symbol'], 'score': score})
        if len(valid) == len(weights):
            score = sum(valid[key] * weight for key, weight in weights.items()) / denominator
            scores['combined'].append({'symbol': candidate['symbol'], 'score': score})
    reports = {}
    for key, items in scores.items():
        ordered = sorted(items, key=lambda item: (-item['score'], item['symbol']))
        for tier, threshold in enumerate(thresholds):
            matches = [item for item in ordered if item['score'] >= threshold]
            if matches:
                break
        reports[key] = {'items': matches[:10], 'matched': len(matches),
                        'eligible': len(ordered), 'relaxation_tier': tier}
    return reports


def adjusted_stock_returns(history, sessions):
    """Build close-to-close returns, leaving gaps on both sides of a missing bar.

    Sessions come from the verified exchange calendar and must include one
    preceding session for the first requested return.
    """
    sessions = pd.DatetimeIndex(sessions)
    if not sessions.is_unique or not sessions.is_monotonic_increasing or sessions.hasnans:
        raise ValueError('valid ordered exchange sessions required')
    days = sessions.strftime('%Y-%m-%d')
    if not days.is_unique:
        raise ValueError('one session timestamp per trading day required')
    prices = pd.Series({row['date']: row['close'] for row in history['rows']}, dtype=float)
    prices = prices.reindex(days)
    prices.index = sessions
    return prices.pct_change(fill_method=None)
