"""Taiwan close-date expectations from persisted exchange calendars; no HTTP in readers."""
from datetime import date, timedelta
from contextvars import ContextVar
from functools import wraps

_snapshot = ContextVar('calendar_read_snapshot', default=None)


def cached_read(key, default=None):
    from app.db import get
    cache = _snapshot.get()
    if cache is None:return get(key,default)
    if key not in cache:cache[key]=get(key,default)
    return cache[key]


def calendar_snapshot(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _snapshot.get() is not None:return function(*args,**kwargs)
        token = _snapshot.set({})
        try:return function(*args,**kwargs)
        finally:_snapshot.reset(token)
    return wrapped


def valid_calendar(row, year):
    if (not isinstance(row, dict) or type(row.get('year')) is not int or row['year'] != year
            or not isinstance(row.get('closed'), list) or not isinstance(row.get('opened'), list)):
        return False
    try:
        days = [date.fromisoformat(d) for d in row['closed'] + row['opened']]
        if any(d.year != year for d in days) or len(set(days)) != len(days):return False
    except (TypeError, ValueError):return False
    return True


def session(day, read):
    overrides = read('recommendations:session_overrides', {})
    if day.isoformat() in overrides:
        value = overrides[day.isoformat()]
        return value if type(value) is bool else None
    row = read('recommendations:calendar:' + str(day.year), {})
    if not valid_calendar(row, day.year):return None
    return str(day) in row['opened'] or (day.weekday() < 5 and str(day) not in row['closed'])


def expected_close(now, read):
    """18:17 Taipei is the existing completed-daily-refresh publication cutoff."""
    day = now.date()
    if (now.hour, now.minute) < (18, 17):day -= timedelta(days=1)
    for _ in range(40):
        state = session(day, read)
        if state is None:return None
        if state:return day
        day -= timedelta(days=1)
    return None


def status(data, now, read):
    expected = expected_close(now, read)
    result = {'expected_date':str(expected) if expected else None,
              'actual_date':data.get('date'), 'state':'calendar_missing',
              'reason':'缺少可核對的交易日曆，暫停買入分級'}
    if expected is None:return result
    try:actual = date.fromisoformat(data['date'])
    except (KeyError, ValueError, TypeError):
        return {**result,'state':'invalid_date','reason':'行情日期無效'}
    # A verified same-day close may arrive before the scheduled 18:17 refresh.
    early_close = (actual == now.date() and (now.hour, now.minute) >= (13, 30)
                   and session(actual, read) is True)
    valid = actual == expected or early_close
    return {**result,'state':'current' if valid else 'outdated',
            'reason':'符合最近應有收盤日' if valid else '行情未達最近應有收盤日或日期異常'}
