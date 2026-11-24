"""Produce a bounded-cache scan of downside hit rates for verified Taiwan stocks."""
import json
import sys
from time import monotonic

import pandas as pd

from app.db import get, get_many, init_db, leased, put
from app.services.defensive_model import BENCHMARK_WEIGHTS, LOOKBACK_YEARS, adjusted_stock_returns, rank_candidates
from app.services.defensive_research import market_context
from app.services.freshness import local_now

SNAPSHOT = 'defensive:market_ranking'


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
        for offset in range(0, len(symbols), 32):
            keys = {'defensive:adjusted:' + symbol: symbol for symbol in symbols[offset:offset + 32]}
            histories = get_many(keys)
            for key, symbol in keys.items():
                history = histories.get(key, {})
                if history.get('as_of') == str(end) and history.get('rows'):
                    stock = adjusted_stock_returns(history, closes)
                    coverage['current_history'] += 1
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
                            candidates[years].append({'symbol': symbol, 'eligible': True, 'scores': scores})
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
            'thresholds': [.60, .55, .50], 'min_pairs': 60, 'min_down_sessions': 20,
            'periods': {str(years): rank_candidates(rows, (.60, .55, .50))
                        for years, rows in candidates.items()},
        }
        put(SNAPSHOT, result)
        return result


if __name__ == '__main__':
    result = run(progress=lambda value: print(json.dumps(value), file=sys.stderr, flush=True))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if result['state'] == 'evaluated' else 1)
