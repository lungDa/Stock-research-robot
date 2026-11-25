"""Resumable five-year adjusted history using free prices and verified corporate actions."""
import argparse
from datetime import date, timedelta
import json
import os
import re
import time

from app.db import get, get_many, init_db, leased, put, put_many
from app.providers.annual_free import FINMIND, finite, valid_day
from app.providers.bounded_http import ResourceLimitError, fetch_json
from app.providers.corporate_actions import CATALOG_FEEDS, FEEDS, adjust, compact, request_parameters
from app.providers.date_windows import covers, replace_window
from app.providers.finmind_batch import SourceRejected
from app.providers.source_errors import describe
from app.services.data_queue import source_slot
from app.services.freshness import local_now
from app.services.market_recommendations import calendar
from app.services.trading_calendar import expected_close, session, valid_calendar

DATASET = 'TaiwanStockPrice'
SOURCE = 'FinMind / TaiwanStockPrice + verified corporate action references'
STAGING = 'defensive:free_history:'
CATALOG_CONTRACT = 'whole_catalog_v1'
CATALOG_PREFIX = 'defensive:action_catalog:'
PREFIX = 'defensive:adjusted:'


def price_rows(payload, symbol, start, end, read):
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
    return rows


def parse(payload, symbol, start, end, read):
    rows = price_rows(payload, symbol, start, end, read)
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
    return {'symbol': symbol, 'source': SOURCE,
            'as_of': str(end), 'coverage': coverage,
            'rows': [rows[day] for day in sorted(rows)]}


def anniversary(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def next_window(state, start, end, limit_days=366):
    """Select the first uncovered interval, bounded by the last successful request size."""
    cursor = start
    for window in sorted(state.get('coverage_windows', []), key=lambda w: w['start']):
        a, b = date.fromisoformat(window['start']), date.fromisoformat(window['end'])
        if b < cursor:
            continue
        if a > cursor:
            end = min(end, a - timedelta(days=1))
            break
        cursor = max(cursor, b + timedelta(days=1))
        if cursor > end:
            return None
    if cursor > end:
        return None
    limit = max(1, min(int(state.get('window_days', limit_days)), limit_days))
    return {'start': str(cursor), 'end': str(min(end, cursor + timedelta(days=limit-1)))}


def merge_coverage(windows, start):
    """Compact adjoining verified intervals; keep at most the retained history."""
    merged = []
    for window in sorted(windows, key=lambda value: value['start']):
        a = max(date.fromisoformat(window['start']), start)
        b = date.fromisoformat(window['end'])
        if a > b:
            continue
        if merged and a <= date.fromisoformat(merged[-1]['end']) + timedelta(days=1):
            merged[-1]['end'] = max(merged[-1]['end'], str(b))
        else:
            merged.append({'start':str(a), 'end':str(b)})
    return merged


def assemble(symbol, start, end, states, read):
    """Publish only when price and all four event intervals have been verified."""
    if not all(covers(states[feed].get('coverage_windows', []), start, end)
               for feed in (DATASET, *FEEDS)):
        return None
    raw = [row for row in states[DATASET]['records'] if str(start) <= row['date'] <= str(end)]
    feeds = {feed: {**states[feed], 'status':'ok', 'events': states[feed]['records']} for feed in FEEDS}
    adjusted, events = adjust(raw, feeds, symbol)
    days = [date.fromisoformat(row['date']) for row in adjusted]
    for event in events:
        day = date.fromisoformat(event['date'])
        previous = day - timedelta(days=1)
        while previous >= start and session(previous, read) is False:
            previous -= timedelta(days=1)
        if previous not in days or day not in days or days.index(day) - days.index(previous) != 1:
            raise ValueError('corporate action previous trading session is missing')
    data = []
    for row in adjusted:
        factor = row['adjustment_factor']
        data.append({'date':row['date'], 'stock_id':symbol.split('.')[0],
                     'open':row['open'] * factor, 'close':row['adjusted_close']})
    if any(abs(b['close']/a['close'] - 1) > .30 for a,b in zip(data, data[1:])):
        raise ValueError('unexplained adjusted price jump')
    history = parse({'status':200,'data':data}, symbol, start, end, read)
    history['raw_rows'] = sorted(raw, key=lambda row: row['date'])
    history['adjustment_events'] = events
    history['price_basis'] = 'latest_price_adjusted'
    history['catalog_contract'] = CATALOG_CONTRACT
    return history


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
            previous = get(key, {})
            if previous.get('as_of') == str(end) and previous.get('source') == SOURCE and previous.get('catalog_contract') == CATALOG_CONTRACT:
                results[symbol] = {'state': 'cached', 'coverage': previous['coverage']}
                continue
            keys = {feed: STAGING + symbol + ':' + feed for feed in (DATASET, *FEEDS)}
            saved = get_many(keys.values())
            states = {feed: saved.get(doc_key, {}) for feed, doc_key in keys.items()}
            for catalog_feed in CATALOG_FEEDS:
                if states[catalog_feed].get('catalog_contract') != CATALOG_CONTRACT:
                    states[catalog_feed] = {}
            missing = [(feed, next_window(state, start, end, 366 if feed == DATASET else 1830))
                       for feed, state in states.items()]
            missing = [(feed, window) for feed, window in missing if window is not None]
            if missing:
                # Each symbol advances one verified source window per call.
                available = [(feed, window) for feed, window in missing
                             if stamp >= states[feed].get('next_attempt', 0)]
                if not available:
                    results[symbol] = {'state':'cooldown'}
                    continue
                feed, window = available[0]
                state = states[feed]
                catalog = get(CATALOG_PREFIX + feed, {}) if feed in CATALOG_FEEDS else {}
                cached_catalog = (catalog.get('catalog_contract') == CATALOG_CONTRACT and
                    covers(catalog.get('coverage_windows', []), window['start'], window['end']))
                try:
                    if cached_catalog:
                        payload = {'status':200,'data':catalog['records']}
                    else:
                        if stamp < get('annual:source:finmind', {}).get('next_attempt', 0):
                            results[symbol] = {'state':'cooldown'}
                            continue
                        if not source_slot('defensive_history', 24) or not source_slot('finmind', 100):
                            results[symbol] = {'state':'budget'}
                            break
                        payload = fetch_json(FINMIND, request_parameters(feed, symbol, window['start'], window['end']),
                                             headers={'Authorization':'Bearer ' + token},
                                             max_bytes=786432, seconds=10, socket_timeout=(3,4))
                    if not isinstance(payload, dict) or payload.get('status') != 200:
                        raise SourceRejected(payload.get('status') if isinstance(payload, dict) else None)
                    if feed == DATASET:
                        price = price_rows(payload, symbol, date.fromisoformat(window['start']),
                                           date.fromisoformat(window['end']), read)
                        if window['end'] == str(end) and end not in price:
                            raise ValueError('latest verified session is missing')
                        records = list(price.values())
                    else:
                        raw_events = payload.get('data')
                        if feed in CATALOG_FEEDS:
                            if not isinstance(raw_events, list) or not raw_events:
                                raise ValueError('whole company action catalog is empty or invalid')
                            if not cached_catalog:
                                put(CATALOG_PREFIX + feed, {'records':raw_events,
                                    'coverage_windows':[{'start':window['start'],'end':str(end)}],
                                    'catalog_contract':CATALOG_CONTRACT})
                            state = {**state,'catalog_contract':CATALOG_CONTRACT}
                        records = compact(feed, raw_events, symbol, window['start'], window['end'])
                    state = {**state, 'records':[row for row in replace_window(state.get('records', []), records, window)
                                        if row['date'] >= str(start)],
                             'coverage_windows':merge_coverage(state.get('coverage_windows', []) + [window], start),
                             'next_attempt':0}
                    states[feed] = state
                    put(keys[feed], state)
                except ResourceLimitError as exc:
                    if feed in CATALOG_FEEDS:
                        put(keys[feed], {**state,'catalog_contract':CATALOG_CONTRACT,'next_attempt':stamp+3600})
                        results[symbol] = {'state':'failed','feed':feed,'reason':'catalog_exceeded_budget'}
                        continue
                    days = (date.fromisoformat(window['end']) - date.fromisoformat(window['start'])).days + 1
                    put(keys[feed], {**state,'window_days':max(1, days//2),'next_attempt':stamp+60 if days>1 else stamp+3600})
                    results[symbol] = {'state':'backfilling','feed':feed,'reason':'window_split' if days>1 else 'window_limit'}
                    continue
                except Exception as exc:
                    detail = describe(exc, '台股原始行情／公司行動')
                    put(keys[feed], {**state,'next_attempt':stamp+3600,'last_failure':detail,
                                     **({'catalog_contract':CATALOG_CONTRACT} if feed in CATALOG_FEEDS else {})})
                    if detail['error_code'] in ('http_401', 'http_403', 'http_429'):
                        put('annual:source:finmind', {'next_attempt':stamp+86400})
                    results[symbol] = {'state':'failed','feed':feed,**detail}
                    continue
            try:
                history = assemble(symbol, start, end, states, read)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                results[symbol] = {'state':'failed', **describe(exc, '台股還原驗證')}
                continue
            if history is None:
                results[symbol] = {'state':'backfilling','feed':feed,
                                   'completed_feeds':sum(covers(s.get('coverage_windows', []), start, end)
                                                         for s in states.values()),
                                   'total_feeds':len(states)}
                continue
            put(key, history)
            results[symbol] = {'state':'updated','coverage':history['coverage']}
        return {'state':'finished' if len(results)==len(symbols) and all(
                    row['state'] in ('cached','updated') for row in results.values()) else 'partial',
                'as_of':str(end),'symbols':results}


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
