"""TWSE daily sector price indices from the indices-only MI_INDEX report."""
from app.providers.taiwan_official import _request, numeric

URL = 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX'
NAMES = {'電子工業類指數': 'tw_electronics', '半導體類指數': 'tw_semiconductors'}


def parse(payload, day):
    requested = day.strftime('%Y%m%d')
    if (not isinstance(payload, dict) or payload.get('stat') != 'OK'
            or payload.get('date') != requested or payload.get('type') != 'IND'):
        raise ValueError('TWSE index report date or type mismatch')
    title = f'{day.year - 1911}年{day.month:02d}月{day.day:02d}日 價格指數(臺灣證券交易所)'
    reports = payload.get('tables')
    if not isinstance(reports, list):
        raise ValueError('TWSE index report tables mismatch')
    tables = [table for table in reports if isinstance(table, dict) and table.get('title') == title]
    if len(tables) != 1:
        raise ValueError('TWSE domestic price index table missing or ambiguous')
    table = tables[0]
    fields = table.get('fields', [])
    if not isinstance(fields, list) or fields[:2] != ['指數', '收盤指數']:
        raise ValueError('TWSE price index fields mismatch')
    values = {}
    data = table.get('data')
    if not isinstance(data, list):
        raise ValueError('TWSE price index rows mismatch')
    for row in data:
        if isinstance(row, list) and row and isinstance(row[0], str) and row[0] in NAMES:
            key = NAMES[row[0]]
            close = numeric(row[1]) if len(row) == len(fields) else None
            if key in values or close is None or close <= 0:
                raise ValueError('TWSE sector close is invalid or duplicated')
            values[key] = close
    if set(values) != set(NAMES.values()):
        raise ValueError('TWSE sector close is missing')
    return values


def fetch(day):
    return parse(_request(URL, {'date': day.strftime('%Y%m%d'), 'type': 'IND',
                                'response': 'json'}), day)
