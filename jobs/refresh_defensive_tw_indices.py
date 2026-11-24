"""Fill two verified Taiwan index series with at most two daily reports per run."""
from datetime import timedelta
import json

from app.db import get, init_db, leased, put, put_many
from app.providers import twse_indices
from app.providers.source_errors import describe
from app.services.freshness import TAIPEI, local_now
from app.services.trading_calendar import calendar_snapshot, cached_read, expected_close, session, valid_calendar
from jobs.refresh_defensive_history import anniversary, fill_calendar

HISTORY = 'defensive:tw_indices'
FAILURES = HISTORY + ':retry'


@calendar_snapshot
def run(now=None):
    now = now or local_now()
    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    now = now.astimezone(TAIPEI)
    stamp = now.timestamp()
    init_db()
    with leased(HISTORY + ':worker', 90) as acquired:
        if not acquired:
            return {'state': 'busy'}
        end = expected_close(now, cached_read)
        if end is None:
            for year in (now.year, now.year - 1):
                if not valid_calendar(cached_read(f'recommendations:calendar:{year}', {}), year):
                    return fill_calendar(year)
            return {'state': 'calendar_missing'}
        start = anniversary(end, 5) - timedelta(days=7)
        days = []
        day = end
        while day >= start:
            active = session(day, cached_read)
            if active is None:
                return fill_calendar(day.year)
            if active:
                days.append(day)
            day -= timedelta(days=1)
        previous = get(HISTORY, {})
        rows = {key: value for key, value in previous.get('rows', {}).items()
                if str(start) <= key <= str(end)}
        retry = {key: until for key, until in get(FAILURES, {}).items() if until > stamp}
        pending = [day for day in days if str(day) not in rows and str(day) not in retry]
        errors = []
        for day in pending[:2]:
            key = str(day)
            try:
                values = twse_indices.fetch(day)
            except (ValueError, OSError, RuntimeError) as exc:
                retry[key] = stamp + 3600
                errors.append({'date': key, **describe(exc, '證交所類股指數')})
                continue
            rows[key] = {'closes': values, 'observed_at': local_now().isoformat()}
            put_many({HISTORY: {'source': twse_indices.URL, 'rows': rows}, FAILURES: retry})
        if errors:
            put(FAILURES, retry)
        observed = sum(str(day) in rows for day in days)
        return {'state': 'finished' if observed == len(days) else 'partial',
                'sessions': len(days), 'observed': observed, 'errors': errors}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False))
