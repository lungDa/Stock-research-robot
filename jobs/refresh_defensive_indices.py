"""Download the two US benchmarks into the defensive research cache."""
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

from app.db import get, init_db, leased, put
from app.providers import fred_indices, us_index_observations
from app.providers.source_errors import describe

NEW_YORK = ZoneInfo('America/New_York')
PREFIX = 'defensive:index:'


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
            if 0 <= now.timestamp() - cached.get('checked_at', 0) < 3600:
                results[benchmark] = {'state': 'cached', 'latest': cached['rows'][-1]['date']}
                continue
            try:
                rows = fred_indices.fetch(benchmark, start, end)
                if cached and rows[-1]['date'] < cached['rows'][-1]['date']:
                    raise ValueError('FRED latest observation regressed')
            except (ValueError, OSError, RuntimeError) as exc:
                results[benchmark] = {'state': 'failed', **describe(exc, '美股指數歷史')}
                continue
            observed_at = now if fixed_clock else datetime.now(timezone.utc)
            availability = us_index_observations.availability(rows, cached, closes, observed_at)
            put(key, {**availability, 'series': series, 'source': f'https://fred.stlouisfed.org/series/{series}',
                      'checked_at': observed_at.timestamp(), 'rows': rows})
            results[benchmark] = {'state': 'updated', 'latest': rows[-1]['date'],
                                  'observations': len(rows), 'timed_observations': len(availability['published_at'])}
    return {'state': 'partial' if any(row['state'] == 'failed' for row in results.values())
            else 'finished', 'indices': results}


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['state'] == 'finished' else 1)
