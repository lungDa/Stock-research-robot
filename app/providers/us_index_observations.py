"""Record when FRED daily close values were first seen by this worker."""
from datetime import time
from zoneinfo import ZoneInfo

import exchange_calendars
import pandas as pd

NEW_YORK = ZoneInfo('America/New_York')


def session_closes(start, end):
    calendar = exchange_calendars.get_calendar('XNYS', start=str(start), end=str(end))
    return calendar.schedule['close']


def availability(rows, previous, closes, observed_at):
    """Only assign a first-seen timestamp to the latest completed session."""
    old_prices = {row['date']: row['close'] for row in previous.get('rows', [])}
    old_times = previous.get('published_at', {})
    session_days = set(closes.index.strftime('%Y-%m-%d'))
    times = {}
    for row in rows:
        day = row['date']
        if day in old_times and day in session_days and old_prices.get(day) == row['close']:
            times[day] = old_times[day]

    latest = rows[-1]['date']
    if latest == latest_completed_session(closes, observed_at):
        times.setdefault(latest, observed_at.isoformat())
    return {'session_closes': [pd.Timestamp(stamp).isoformat() for stamp in closes],
            'published_at': times, 'availability_basis': 'worker_first_seen'}


def latest_completed_session(closes, observed_at):
    # Use 16:00 ET as a conservative boundary even on shortened sessions.
    local = observed_at.astimezone(NEW_YORK)
    completed = closes[closes <= observed_at]
    if local.time() < time(16):
        completed = completed[completed.index.strftime('%Y-%m-%d') < str(local.date())]
    return str(completed.index[-1].date()) if not completed.empty else None
