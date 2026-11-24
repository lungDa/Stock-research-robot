"""Read-only latency and coverage audit of the persisted defensive research data."""
import argparse
import json
from math import ceil
from time import perf_counter

from sqlalchemy.exc import SQLAlchemyError

from app.db import engine, get, get_many
from app.services.defensive_model import BENCHMARK_WEIGHTS, LOOKBACK_YEARS
from app.services.defensive_notifications import RISK_SNAPSHOT
from app.services.defensive_research import market_context
from app.services.freshness import TAIPEI, local_now
from app.services.trading_calendar import cached_read, calendar_snapshot, expected_close
from jobs.rank_defensive_market import SNAPSHOT

CATALOG = 'v26:universe:verified_symbols'


def measure(read, *, samples, limit, validate):
    times = []
    usable = 0
    value = None
    for _ in range(samples):
        start = perf_counter()
        value = read()
        times.append(perf_counter() - start)
        usable += bool(validate(value))
    p95 = sorted(times)[ceil(samples * .95) - 1]
    return value, {
        'samples': samples, 'usable_samples': usable,
        'p95_seconds': round(p95, 6), 'limit_seconds': limit,
        'state': 'insufficient_data' if usable != samples else 'passed' if p95 <= limit else 'failed',
    }


def benchmark_readiness(now):
    docs, end, closes, benchmarks = market_context(now, history_days=45)
    sectors = docs.get('defensive:tw_indices', {}).get('rows', {})
    reports = {}
    for key in BENCHMARK_WEIGHTS:
        if key.startswith('tw_'):
            days = [day for day, item in sectors.items() if key in item.get('closes', {})]
            times = None
        else:
            history_key = ('defensive:adjusted:' if key == '2330.TW' else 'defensive:index:') + key
            history = docs.get(history_key, {})
            days = [row['date'] for row in history.get('rows', [])]
            times = len(history.get('published_at', {})) if key != '2330.TW' else None
        series, details = benchmarks.get(key, (None, {'state': 'calendar_missing'}))
        state = details['state']
        if series is not None:
            state = 'return_ready' if series.notna().iloc[-1] else 'session_return_missing'
        reports[key] = {'state': state, 'stored_closes': len(days),
                        'latest_stored_close': max(days, default=None), 'stored_time_records': times,
                        'usable_returns_in_window': int(series.notna().sum()) if series is not None else None}
    return {'calendar_window_days': 45, 'target_session': str(end) if end else None,
            'benchmarks': reports}


@calendar_snapshot
def run(now=None, *, samples=20):
    now = now or local_now()
    if now.tzinfo is None or type(samples) is not int or not 1 <= samples <= 100:
        raise ValueError('timezone-aware clock and 1–100 samples required')
    now = now.astimezone(TAIPEI)
    target = expected_close(now, cached_read)
    current = str(target) if target is not None else None
    stock_key = 'defensive:adjusted:2330.TW'
    _, quote = measure(lambda: get(stock_key), samples=samples, limit=1,
                       validate=lambda row: bool(current and row and row.get('as_of') == current and row.get('rows')))
    _, batch = measure(lambda: get_many([stock_key, CATALOG]), samples=samples, limit=3,
                       validate=lambda docs: bool(docs.get(stock_key) and docs.get(CATALOG)))
    snapshot, ranking = measure(lambda: get(SNAPSHOT), samples=samples, limit=5, validate=lambda row: bool(
        current and row and row.get('state') == 'evaluated' and row.get('as_of') == current
        and row.get('coverage', {}).get('current_history', 0)
        and any(board.get('eligible', 0) > 0 for period in row.get('periods', {}).values()
                for board in period.values())
    ))
    catalog = get(CATALOG, {})
    age = now.timestamp() - catalog.get('at', 0)
    symbols = sorted(set(catalog.get('symbols', [])))
    verified = catalog.get('verified') is True and 0 <= age <= 48 * 3600 and bool(symbols)
    history_count = 0
    periods = {str(years): {'observed': 0, 'sessions': 0, 'stocks_with_counts': 0} for years in LOOKBACK_YEARS}
    if verified and current:
        for offset in range(0, len(symbols), 32):
            keys = ['defensive:adjusted:' + symbol for symbol in symbols[offset:offset + 32]]
            for row in get_many(keys).values():
                if row.get('as_of') != current or not row.get('rows'):
                    continue
                history_count += 1
                for years, counts in periods.items():
                    item = row.get('coverage', {}).get(years, {})
                    observed, expected = item.get('observed'), item.get('sessions')
                    if type(observed) is int and type(expected) is int and 0 <= observed <= expected and expected > 0:
                        counts['observed'] += observed
                        counts['sessions'] += expected
                        counts['stocks_with_counts'] += 1
    for counts in periods.values():
        counts['observed_ratio'] = counts['observed'] / counts['sessions'] if counts['sessions'] else None
    risk = get(RISK_SNAPSHOT, {})
    risk_day = risk.get('session_date') if risk.get('verified') is True else None
    return {
        'benchmark_readiness': benchmark_readiness(now),
        'risk_snapshot': {'as_of': risk_day, 'matches_target': bool(current and risk_day == current)},
        'audit_time': now.isoformat(), 'database': engine.dialect.name, 'target_session': current,
        'latency': {'cached_history_read': quote, 'database_batch_read': batch,
                    'precomputed_ranking_read': ranking},
        'coverage': {'verified_universe': verified, 'total_stocks': len(symbols) if verified else None,
                     'current_adjusted_stocks': history_count if current and verified else None,
                     'current_history_ratio': history_count / len(symbols) if current and verified else None,
                     'historical_counts_for_current_stocks': periods,
                     'published_applicable_data_99_percent': 'unverified'},
        'ranking_as_of': snapshot.get('as_of') if snapshot else None,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=20)
    args = parser.parse_args()
    try:
        result = run(samples=args.samples)
    except (ValueError, OSError, SQLAlchemyError):
        parser.exit(1, 'Audit could not read valid data.\n')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
