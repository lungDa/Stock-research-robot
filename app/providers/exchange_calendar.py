"""Year-pinned TWSE holiday schedules; never relabel the latest year."""
from datetime import date
import re

URL = 'https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule'


def parse(payload, year):
    if not isinstance(payload, dict) or payload.get('stat') != 'ok':
        raise ValueError('交易日曆不可用')
    if payload.get('date') != f'{year}0101' or payload.get('queryYear') != year:
        raise ValueError('交易日曆年度不符')
    if not re.fullmatch(rf'\s*{year-1911}\s*年市場開休市日期\s*', str(payload.get('title', ''))):
        raise ValueError('交易日曆標題年度不符')
    fields = payload.get('fields')
    rows = payload.get('data')
    if (not isinstance(fields, list) or not all(isinstance(f,str) for f in fields)
            or len(set(fields)) != len(fields)
            or not all(f in fields for f in ('日期', '名稱', '說明'))
            or not isinstance(rows, list) or not rows
            or type(payload.get('total')) is not int or payload['total'] != len(rows)):
        raise ValueError('交易日曆欄位或筆數不完整')
    opened, closed = set(), set()
    for row in rows:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError('交易日曆資料列不完整')
        record = dict(zip(fields, row))
        day = date.fromisoformat(record['日期'])
        if day.year != year:
            raise ValueError('交易日曆年度不符')
        name = record['名稱']
        if not isinstance(name, str) or not name.strip():
            raise ValueError('交易日曆名稱缺失')
        # Descriptions can mention *other* dates without trading. The row's
        # own name determines whether its date is an opening/last session.
        is_open = ('開始交易' in name or '最後交易' in name) and '無交易' not in name
        target = opened if is_open else closed
        other = closed if is_open else opened
        if str(day) in target or str(day) in other:
            raise ValueError('交易日曆日期重複或衝突')
        target.add(str(day))
    if len(closed) < 5 or not opened:
        raise ValueError('交易日曆不完整')
    return {'year': year, 'closed': sorted(closed), 'opened': sorted(opened),
            'source': URL, 'source_date': payload['date']}


def load(year):
    from app.providers.bounded_http import fetch_json
    date(year, 1, 1)  # Validate the requested Gregorian year before HTTP.
    payload = fetch_json(URL, {'date': f'{year}0101', 'response': 'json'},
                         max_bytes=65536, seconds=12, socket_timeout=(8,3))
    return parse(payload, year)
