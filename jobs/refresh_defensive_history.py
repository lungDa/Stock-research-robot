"""Bounded backfill of five-year adjusted Taiwan stock history for research."""
import argparse
from datetime import timedelta
import json
import os
import re
import time

from app.db import get, init_db, leased, put, put_many
from app.providers.annual_free import FINMIND, finite, valid_day
from app.providers.bounded_http import fetch_json
from app.providers.finmind_batch import SourceRejected
from app.providers.source_errors import describe
from app.services.data_queue import source_slot
from app.services.freshness import local_now
from app.services.market_recommendations import calendar
from app.services.trading_calendar import expected_close, session, valid_calendar

DATASET = 'TaiwanStockPriceAdj'
PREFIX = 'defensive:adjusted:'


def parse(payload, symbol, start, end, read):
    if not isinstance(payload, dict) or payload.get('status') != 200:
        raise SourceRejected(payload.get('status') if isinstance(payload, dict) else None)
    if not isinstance(payload.get('data'), list):
        raise ValueError('invalid adjusted history')
    code = symbol.split('.')[0]
    rows = {}
    for raw in payload['data']:
        if not isinstance(raw, dict) or str(raw.get('stock_id')) != code:
            raise ValueError('adjusted history company mismatch')
        day = valid_day(raw.get('date'))
        if day is None or not start <= day <= end or session(day, read) is not True:
            raise ValueError('adjusted history date is outside verified sessions')
        opening, close = (finite(raw.get(field)) for field in ('open', 'close'))
        if opening is None or close is None or min(opening, close) <= 0:
            raise ValueError('invalid adjusted price')
        row = {'date': str(day), 'open': opening, 'close': close}
        if day in rows and rows[day] != row:
            raise ValueError('conflicting adjusted history rows')
        rows[day] = row
    if end not in rows:
        raise ValueError('latest verified session is missing')
    coverage = {}
    for years in (1, 3, 5):
        boundary = anniversary(end, years)
        expected = observed = 0
        day = boundary + timedelta(days=1)
        while day <= end:
            active = session(day, read)
            if active is None:
                raise ValueError('verified historical trading calendar required')
            expected += active
            observed += day in rows
            day += timedelta(days=1)
        coverage[str(years)] = {'sessions': expected, 'observed': observed,
                                'ratio': observed / expected if expected else None}
    return {'symbol': symbol, 'source': 'FinMind / ' + DATASET,
            'as_of': str(end), 'coverage': coverage,
            'rows': [rows[day] for day in sorted(rows)]}


def anniversary(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def run(symbols):
    symbols = list(dict.fromkeys(symbols))
    if not 1 <= len(symbols) <= 2 or any(
        not re.fullmatch(r'\d{4,6}[A-Z]?\.(TW|TWO)', symbol) for symbol in symbols
    ):
        raise ValueError('supply one or two Taiwan symbols with exchange suffix')
    token = os.getenv('FINMIND_TOKEN', '').strip()
    if not token:
        return {'state': 'not_configured'}
    init_db()
    with leased('annual:worker', 180) as acquired:
        if not acquired:
            return {'state': 'busy'}
        now = local_now()
        stamp = time.time()
        calendar_cache = {}

        def read(key, default=None):
            if key not in calendar_cache:
                calendar_cache[key] = get(key, default)
            return calendar_cache[key]

        end = expected_close(now, read)
        if end is None:
            missing_year = next((year for year in (now.year, now.year - 1)
                                 if not valid_calendar(read(f'recommendations:calendar:{year}', {}), year)), None)
            if missing_year is None:
                return {'state': 'calendar_missing'}
            return fill_calendar(missing_year)
        start = anniversary(end, 5)
        for year in range(start.year, end.year + 1):
            if not valid_calendar(read(f'recommendations:calendar:{year}', {}), year):
                return fill_calendar(year)
        results = {}
        for symbol in symbols:
            key = PREFIX + symbol
            state_key = 'defensive:history_state:' + symbol
            previous = get(key, {})
            if previous.get('as_of') == str(end):
                results[symbol] = {'state': 'cached', 'coverage': previous['coverage']}
                continue
            if stamp < max(get(state_key, {}).get('next_attempt', 0),
                           get('annual:source:finmind', {}).get('next_attempt', 0)):
                results[symbol] = {'state': 'cooldown'}
                continue
            if not source_slot('finmind', 100):
                results[symbol] = {'state': 'budget'}
                break
            put(state_key, {'next_attempt': stamp + 3600})
            try:
                payload = fetch_json(FINMIND, {'dataset': DATASET, 'data_id': symbol.split('.')[0],
                                               'start_date': str(start), 'end_date': str(end)},
                                     headers={'Authorization': 'Bearer ' + token},
                                     max_bytes=786432, seconds=10, socket_timeout=(3, 4))
                history = parse(payload, symbol, start, end, read)
            except Exception as exc:
                detail = describe(exc, '台股還原歷史')
                if detail['error_code'] in ('http_401', 'http_403', 'http_429'):
                    put('annual:source:finmind', {'next_attempt': stamp + 86400})
                results[symbol] = {'state': 'failed', **detail}
                continue
            put_many({key: history, state_key: {'next_attempt': 0}})
            results[symbol] = {'state': 'updated', 'coverage': history['coverage']}
        return {'state': 'finished' if all(row['state'] in ('cached', 'updated')
                                           for row in results.values()) else 'partial',
                'as_of': str(end), 'symbols': results}


def fill_calendar(year):
    try:
        calendar(year)
    except Exception as exc:
        return {'state': 'calendar_failed', 'year': year, **describe(exc, '歷史交易日曆')}
    return {'state': 'calendar_updated', 'year': year}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('symbols', nargs='+')
    args = parser.parse_args()
    result = run(args.symbols)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['state'] in ('finished', 'calendar_updated') else 1)
