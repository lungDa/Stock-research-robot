"""Read-only latency and coverage audit of the persisted defensive research data."""
import argparse
import json
from math import ceil
from time import perf_counter

from sqlalchemy.exc import SQLAlchemyError

from app.db import engine, get, get_many
from app.services.defensive_model import LOOKBACK_YEARS
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
    return {
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
