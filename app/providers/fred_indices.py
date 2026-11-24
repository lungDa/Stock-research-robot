"""Validated daily US index closes. FRED dates carry no publication time."""
import csv
from datetime import date
from io import StringIO
from time import monotonic

import requests

from app.providers.annual_free import finite, valid_day
from app.providers.bounded_http import ResourceLimitError

SERIES = {'nasdaq_100': 'NASDAQ100', 'sox': 'NASDAQSOX'}
URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv'
MAX_BYTES = 96 * 1024


def parse_csv(body, series, start, end):
    reader = csv.reader(StringIO(body))
    if next(reader, []) not in (['observation_date', series], ['DATE', series]):
        raise ValueError('FRED series header mismatch')
    rows = []
    previous = date.min
    for row in reader:
        if len(row) != 2:
            raise ValueError('invalid FRED row')
        day = valid_day(row[0])
        if day is None or not start <= day <= end or day <= previous:
            raise ValueError('FRED dates must be unique, ordered and inside requested range')
        previous = day
        if row[1] in ('', '.'):
            continue
        close = finite(row[1])
        if close is None or close <= 0:
            raise ValueError('invalid FRED close')
        rows.append({'date': str(day), 'close': close})
    if not rows:
        raise ValueError('no FRED index closes')
    return rows


def fetch(benchmark, start, end):
    series = SERIES[benchmark]
    params = {'id': series, 'cosd': str(start), 'coed': str(end)}
    deadline = monotonic() + 15
    with requests.get(URL, params=params, stream=True, timeout=(4, 9),
                      allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('unexpected FRED response')
        body = bytearray()
        for chunk in response.iter_content(8192):
            if monotonic() >= deadline:
                raise ResourceLimitError('FRED response exceeds time budget')
            if len(body) + len(chunk) > MAX_BYTES:
                raise ResourceLimitError('FRED response exceeds size budget')
            body.extend(chunk)
    return parse_csv(body.decode('utf-8-sig'), series, start, end)
