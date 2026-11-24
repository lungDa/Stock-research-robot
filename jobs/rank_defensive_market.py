"""Produce a bounded-cache scan of downside hit rates for verified Taiwan stocks."""
import argparse
import json
from operator import eq, ge, gt
import sys
from time import monotonic

import pandas as pd

from app.db import get, get_many, init_db, leased, put
from app.services.defensive_model import BENCHMARK_WEIGHTS, LOOKBACK_YEARS, adjusted_stock_returns, rank_candidates
from app.services.defensive_research import market_context
from app.services.freshness import TAIPEI, local_now
from app.services.multifactor import ANNUAL, DEFAULT, annual_rows, value_for
from app.services.trading_calendar import calendar_snapshot, cached_read, expected_close

SNAPSHOT = 'defensive:market_ranking'
ANNUAL_PREFIXES = ('annual:shared:', 'eps:official:', 'financial:official:', 'cashflow:official:')
ANNUAL_RULES = tuple(rule for rule in DEFAULT['stock_rules'] if rule['metric'] in ANNUAL)
COMPARE = {'>': gt, '>=': ge, '==': eq}
THRESHOLDS = (.60, .55, .50)


def screen_candidate(symbol, history, closes, end, docs):
    prices = pd.Series({row['date']: row['close'] for row in history['rows']}, dtype=float)
    prices = prices.reindex(closes[-60:].strftime('%Y-%m-%d'))
    latest = prices.iloc[-1]
    if pd.isna(latest):
        return 'missing_data'
    if len(prices) < 60 or prices.isna().any():
        return 'missing_data'
    ma20, ma60 = prices.tail(20).mean(), prices.mean()
    rows = annual_rows('', symbol, docs)
    for row in rows.values():
        for field, source in row.get('field_sources', {}).items():
            if str(source.get('as_of') or '')[:10] > str(end):
                row.pop(field, None)
    values = [value_for({}, rows, rule['metric'], rule['years'], end) for rule in ANNUAL_RULES]
    if any(value is None for value in values):
        return 'missing_data'
    annual_ok = all(COMPARE[rule['op']](value, rule['threshold'])
                    for rule, value in zip(ANNUAL_RULES, values))
    return 'passed' if annual_ok and latest > ma20 > ma60 else 'failed_rules'


def run(now=None, progress=None):
    now = now or local_now()
    init_db()
    with leased(SNAPSHOT + ':worker', 900) as acquired:
        if not acquired:
            return {'state': 'busy'}
        catalog = get('v26:universe:verified_symbols', {})
        age = now.timestamp() - catalog.get('at', 0)
        symbols = sorted(set(catalog.get('symbols', [])))
        if catalog.get('verified') is not True or not 0 <= age <= 48 * 3600 or not symbols:
            return {'state': 'universe_unverified'}
        _, end, closes, benchmarks = market_context(now)
        if end is None:
            return {'state': 'calendar_missing'}

        windows = {years: closes > closes[-1] - pd.DateOffset(years=years) for years in LOOKBACK_YEARS}
        candidates = {years: [] for years in windows}
        screened = {years: [] for years in windows}
        screen_counts = dict.fromkeys(('passed', 'failed_rules', 'missing_data'), 0)
        fundamentals = get_many(['fundamentals:index:TW', 'fundamentals:index:TWO'])
        eligible = {years: 0 for years in windows}
        coverage = {'universe': len(symbols), 'current_history': 0}
        scanned = 0
        updated = monotonic()

        def update():
            if progress:
                progress({'scanned': scanned, 'total': len(symbols),
                          'percent': round(scanned / len(symbols) * 100, 1),
                          'qualified_by_period': eligible.copy()})

        update()
        for offset in range(0, len(symbols), 16):
            keys = {'defensive:adjusted:' + symbol: symbol for symbol in symbols[offset:offset + 16]}
            histories = get_many(keys)
            annual_keys = [prefix + symbol for key, symbol in keys.items()
                           if histories.get(key, {}).get('as_of') == str(end)
                           for prefix in ANNUAL_PREFIXES]
            documents = {**fundamentals, **get_many(annual_keys)} if annual_keys else fundamentals
            for key, symbol in keys.items():
                history = histories.get(key, {})
                if history.get('as_of') == str(end) and history.get('rows'):
                    stock = adjusted_stock_returns(history, closes)
                    coverage['current_history'] += 1
                    screening = screen_candidate(symbol, history, closes, end, documents)
                    screen_counts[screening] += 1
                    for years, window in windows.items():
                        scores = {}
                        for benchmark in BENCHMARK_WEIGHTS:
                            returns, _ = benchmarks[benchmark]
                            if benchmark == symbol or returns is None:
                                continue
                            pairs = window & stock.notna() & returns.notna()
                            down = pairs & (returns < 0)
                            if pairs.sum() >= 60 and down.sum() >= 20:
                                scores[benchmark] = float((stock[down] > 0).mean())
                        if scores:
                            candidate = {'symbol': symbol, 'eligible': True, 'scores': scores}
                            candidates[years].append(candidate)
                            if screening == 'passed':
                                screened[years].append(candidate)
                            eligible[years] += any(score >= .50 for score in scores.values())
                scanned += 1
                if monotonic() - updated >= 5:
                    update()
                    updated = monotonic()
        update()
        result = {
            'state': 'evaluated', 'as_of': str(end), 'generated_at': now.isoformat(),
            'coverage': coverage, 'benchmark_status': {key: details for key, (_, details) in benchmarks.items()},
            'method': 'historical_downside_hit_rate',
            'thresholds': list(THRESHOLDS), 'min_pairs': 60, 'min_down_sessions': 20,
            'periods': {str(years): rank_candidates(rows, THRESHOLDS) for years, rows in candidates.items()},
            'screen_counts': screen_counts,
            'screened_periods': {str(years): rank_candidates(rows, THRESHOLDS) for years, rows in screened.items()},
        }
        put(SNAPSHOT, result)
        return result


@calendar_snapshot
def run_scheduled(now=None, progress=None):
    now = (now or local_now()).astimezone(TAIPEI)
    init_db()
    end = expected_close(now, cached_read)
    if end is None:
        return {'state': 'calendar_missing'}
    if end != now.date():
        return {'state': 'waiting_for_session_close'}
    previous = get(SNAPSHOT, {})
    if previous.get('state') == 'evaluated' and previous.get('as_of') == str(end):
        return {'state': 'cached', 'as_of': str(end)}
    return run(now, progress)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scheduled', action='store_true')
    args = parser.parse_args()
    rank = run_scheduled if args.scheduled else run
    result = rank(progress=lambda value: print(json.dumps(value), file=sys.stderr, flush=True))
    if args.scheduled and result['state'] == 'evaluated':
        result = {key: result[key] for key in ('state', 'as_of', 'coverage')}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    acceptable = ('evaluated', 'cached', 'waiting_for_session_close', 'busy') if args.scheduled else ('evaluated',)
    raise SystemExit(0 if result['state'] in acceptable else 1)
