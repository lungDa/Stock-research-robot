"""Download the two US benchmarks into the defensive research cache."""
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

from app.db import get, init_db, leased, put
from app.providers import fred_indices, us_index_observations
from app.providers.source_errors import describe

NEW_YORK = ZoneInfo('America/New_York')
PREFIX = 'defensive:index:'
RECENT_DAYS = 14
HISTORY_RETRY_SECONDS = 24 * 3600
CACHE_SECONDS = 55 * 60


def update_rows(benchmark, cached, start, end, now):
    recent = end - timedelta(days=RECENT_DAYS)
    old = cached.get('rows', [])
    loaded = cached.get('historical_window_loaded') is True or (
        bool(old) and old[0]['date'] <= str(start + timedelta(days=30))
    )
    retry_at = cached.get('history_retry_at', 0)
    requested_from = recent if loaded or now.timestamp() < retry_at else start
    history_error = None
    try:
        incoming = fred_indices.fetch(benchmark, requested_from, end)
    except (ValueError, OSError, RuntimeError) as exc:
        if requested_from != start:
            raise
        history_error = describe(exc, '美股指數歷史')['error_code']
        retry_at = now.timestamp() + HISTORY_RETRY_SECONDS
        requested_from = recent
        incoming = fred_indices.fetch(benchmark, requested_from, end)

    if old and incoming[-1]['date'] < old[-1]['date']:
        raise ValueError('FRED latest observation regressed')
    # Replace the requested interval. A missing observation stays missing.
    rows = [row for row in old if str(start) <= row['date'] < str(requested_from)]
    rows.extend(incoming)
    if requested_from == start:
        loaded = True
        retry_at = 0
    return rows, loaded, retry_at, history_error


def run(now=None):
    fixed_clock = now is not None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    end = now.astimezone(NEW_YORK).date()
    start = end - timedelta(days=5 * 366 + 7)
    init_db()
    results = {}
    with leased('defensive:index:worker', 90) as acquired:
        if not acquired:
            return {'state': 'busy'}
        closes = us_index_observations.session_closes(start, end)
        for benchmark, series in fred_indices.SERIES.items():
            key = PREFIX + benchmark
            cached = get(key, {})
            if cached.get('rows') and 0 <= now.timestamp() - cached.get('checked_at', 0) < CACHE_SECONDS:
                results[benchmark] = {'state': 'cached', 'latest': cached['rows'][-1]['date']}
                continue
            try:
                rows, loaded, retry_at, history_error = update_rows(benchmark, cached, start, end, now)
            except (ValueError, OSError, RuntimeError) as exc:
                results[benchmark] = {'state': 'failed', **describe(exc, '美股指數歷史')}
                continue
            observed_at = now if fixed_clock else datetime.now(timezone.utc)
            availability = us_index_observations.availability(rows, cached, closes, observed_at)
            put(key, {**availability, 'series': series, 'source': f'https://fred.stlouisfed.org/series/{series}',
                      'checked_at': observed_at.timestamp(), 'rows': rows,
                      'historical_window_loaded': loaded, 'history_retry_at': retry_at})
            results[benchmark] = {'state': 'updated', 'latest': rows[-1]['date'],
                                  'observations': len(rows), 'timed_observations': len(availability['published_at']),
                                  'history_error': history_error, 'historical_window_loaded': loaded}
    return {'state': 'partial' if any(row['state'] == 'failed' for row in results.values())
            else 'finished', 'indices': results}


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['state'] == 'finished' else 1)
