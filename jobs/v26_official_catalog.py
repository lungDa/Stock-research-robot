"""Official listed/OTC company registries for conservative stock classification.

Registry membership is evidence of a company, not proof that a downloaded
universe covers every security. Unknown codes remain UNKNOWN.
"""
import re
import time
from app.db import get, put
from app.providers.bounded_http import fetch_json

ENDPOINTS = {
    'TW': 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L',
    'TWO': 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O',
}
CODE = re.compile(r'^\d{4}$')
CODE_FIELDS = ('公司代號', '公司代碼', 'CompanyCode', 'SecuritiesCompanyCode')
NAME_FIELDS = ('公司名稱', '公司簡稱', 'CompanyName', 'CompanyShortName')


def parse_companies(payload):
    if not isinstance(payload, list) or not payload:
        raise ValueError('官方公司名錄格式異常')
    found = {}
    recognized = False
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError('公司名錄包含無效資料列')
        keys = set(row)
        if any(field in keys for field in CODE_FIELDS):
            recognized = True
        code = next((str(row[key]).strip() for key in CODE_FIELDS
                     if row.get(key) not in (None, '')), '')
        if not CODE.fullmatch(code):
            continue
        name = next((str(row[key]).strip() for key in NAME_FIELDS
                     if row.get(key) not in (None, '')), '')
        if code in found and found[code]['name'] != name:
            raise ValueError('官方公司名錄代號衝突')
        found[code] = {'kind': 'STOCK', 'name': name}
    if not recognized or not found:
        raise ValueError('官方公司名錄缺少可辨識的公司代號')
    return found


def refresh(market, now=None, fetcher=fetch_json):
    if market not in ENDPOINTS:
        raise ValueError('未知市場')
    now = time.time() if now is None else now
    key = 'official:catalog:' + market
    old = get(key, {})
    if isinstance(old, dict) and old.get('source') == ENDPOINTS[market] and type(old.get('at')) in (int, float) and 0 <= now - old['at'] < 86400:
        return {'market': market, 'status': 'cached', 'count': len(old.get('data', {}))}
    try:
        payload = fetcher(ENDPOINTS[market], max_bytes=8 * 1024 * 1024, seconds=18, array=True)
        data = parse_companies(payload)
    except Exception as exc:
        # A failed fetch must not overwrite an older catalog with an empty list.
        put('v26:catalog:error:' + market, {'at': now, 'error': type(exc).__name__})
        raise
    put(key, {'at': now, 'source': ENDPOINTS[market], 'data': data,
              'scope': 'OFFICIAL_COMPANY_REGISTRY', 'complete': False})
    return {'market': market, 'status': 'updated', 'count': len(data)}


def run():
    results = []
    for market in ('TW', 'TWO'):
        try:
            results.append(refresh(market))
        except Exception as exc:
            results.append({'market': market, 'status': 'failed',
                            'error': type(exc).__name__})
    return results


if __name__ == '__main__':
    from app.db import init_db
    init_db()
    print(run())
