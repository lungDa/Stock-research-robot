"""Read-only downside study across the five cached research benchmarks."""
from datetime import datetime, time, timedelta
from math import isfinite
import re

import pandas as pd

from app.db import get_many
from app.services.defensive_model import (
    BENCHMARK_WEIGHTS, LOOKBACK_YEARS, adjusted_stock_returns,
    align_us_index_history, downside_statistics,
)
from app.services.freshness import TAIPEI
from app.services.trading_calendar import expected_close, session


def report(symbol, now, *, min_pairs=60, severe_drop=.02):
    if not re.fullmatch(r'\d{4,6}[A-Z]?\.(TW|TWO)', symbol):
        raise ValueError('expected a Taiwan stock symbol with exchange suffix')
    if now.tzinfo is None or not isinstance(min_pairs, int) or min_pairs < 2:
        raise ValueError('timezone-aware clock and at least two pairs required')
    if not isfinite(severe_drop) or not 0 < severe_drop <= 1:
        raise ValueError('severe-drop threshold must be within (0, 1]')
    now = now.astimezone(TAIPEI)
    start = (pd.Timestamp(now.date()) - pd.DateOffset(years=max(LOOKBACK_YEARS))).date()
    start -= timedelta(days=14)
    stock_key = 'defensive:adjusted:' + symbol
    tsmc_key = 'defensive:adjusted:2330.TW'
    tw_key = 'defensive:tw_indices'
    us_keys = {key: 'defensive:index:' + key for key in ('nasdaq_100', 'sox')}
    calendar_keys = [f'recommendations:calendar:{year}' for year in range(start.year, now.year + 1)]
    docs = get_many([stock_key, tsmc_key, tw_key, *us_keys.values(),
                     'recommendations:session_overrides', *calendar_keys])
    end = expected_close(now, docs.get)
    if end is None:
        return {'state': 'calendar_missing', 'symbol': symbol}
    days = []
    day = start
    while day <= end:
        active = session(day, docs.get)
        if active is None:
            return {'state': 'calendar_missing', 'symbol': symbol, 'date': str(day)}
        if active:
            days.append(day)
        day += timedelta(days=1)
    closes = _timestamps(days, time(13, 30))
    opens = _timestamps(days, time(9))
    if not docs.get(stock_key, {}).get('rows'):
        return {'state': 'stock_history_missing', 'symbol': symbol, 'as_of': str(end)}
    stock = adjusted_stock_returns(docs[stock_key], closes)
    metrics = {}
    tw_rows = docs.get(tw_key, {}).get('rows', {})
    for key in BENCHMARK_WEIGHTS:
        if key == symbol:
            metrics[key] = {'state': 'self_benchmark'}
            continue
        if key in us_keys:
            history = docs.get(us_keys[key], {})
            if not history.get('rows'):
                metrics[key] = {'state': 'benchmark_history_missing'}
                continue
            if not history.get('session_closes') or not history.get('published_at'):
                metrics[key] = {'state': 'publication_times_missing',
                                'observations': len(history['rows'])}
                continue
            # Only publications seen by the report cutoff may contribute.
            published = {day: stamp for day, stamp in history['published_at'].items()
                         if pd.Timestamp(stamp) <= now}
            us_closes = pd.to_datetime(history['session_closes'], utc=True)
            benchmark = align_us_index_history(history, us_closes, opens, published)
            benchmark.index = closes
            basis = 'us_publication_to_next_tw_open'
        else:
            history = docs.get(tsmc_key) if key == '2330.TW' else {
                'rows': [{'date': day, 'close': item['closes'][key]}
                         for day, item in tw_rows.items() if key in item.get('closes', {})]
            }
            if not history or not history.get('rows'):
                metrics[key] = {'state': 'benchmark_history_missing'}
                continue
            benchmark = adjusted_stock_returns(history, closes)
            basis = 'same_session_close_descriptive'
        periods = {}
        cutoff = closes[-1]
        for years in LOOKBACK_YEARS:
            values = downside_statistics(stock, benchmark, cutoff, years,
                                         severe_drop=severe_drop, min_pairs=min_pairs)
            expected = int((closes > cutoff - pd.DateOffset(years=years)).sum())
            periods[str(years)] = {**values, 'expected_sessions': expected,
                                   'paired_coverage': values['pairs'] / expected if expected else None}
        metrics[key] = {'state': 'evaluated', 'basis': basis, 'periods': periods}
    return {'state': 'evaluated', 'symbol': symbol, 'as_of': str(end),
            'stock_as_of': docs[stock_key].get('as_of'),
            'severe_drop': severe_drop, 'min_pairs': min_pairs, 'benchmarks': metrics}


def _timestamps(days, clock):
    return pd.DatetimeIndex([datetime.combine(day, clock, TAIPEI) for day in days])
