"""共用官方基本面快取。僅排程下載；查詢與LINE不增加外部請求。"""
import re
import time
from datetime import date
from app.db import get, put
from app.providers.taiwan_official import numeric, trading_date
from app.services.freshness import local_now

VERSION = 1
TW = 'https://openapi.twse.com.tw/v1/'
OTC = 'https://www.tpex.org.tw/openapi/v1/'
# 依序輪替，每次最多兩個端點。每個來源只保留解析後的必要欄位。
FEEDS = [('TW', 'fund', TW+'opendata/t187ap47_L'),
         ('TW', 'eps', TW+'opendata/t187ap06_L_ci'),
         ('TWO', 'eps', OTC+'mopsfin_t187ap06_O_ci'),
         ('TW', 'valuation', TW+'exchangeReport/BWIBBU_ALL'),
         ('TWO', 'valuation', OTC+'tpex_mainboard_peratio_analysis'),
         ('TW', 'roe_report', TW+'opendata/t187ap29_C_L'),
         ('TWO', 'roe_report', OTC+'mopsfin_t187ap29_C_O')]
for sector in ('basi', 'bd', 'fh', 'ins', 'mim'):
    FEEDS += [('TW', 'eps', TW+'opendata/t187ap06_L_'+sector),
              ('TWO', 'eps', OTC+'mopsfin_t187ap06_O_'+sector)]


def pick(row, *keys):
    return next((row[k] for k in keys if row.get(k) not in ('', None)), None)


def parse(row, market, category, source, now):
    code = str(pick(row, '基金代號' if category=='fund' else '公司代號',
                    'Code', 'SecuritiesCompanyCode') or '').strip()
    if not re.fullmatch(r'\d{4,6}[A-Z]?', code): return None
    try: asof = trading_date(pick(row, '出表日期', 'Date'))
    except (ValueError, TypeError): return None
    if asof > local_now().date().isoformat(): return None
    meta = {'source': source, 'as_of': asof, 'fetched_at': now}
    fields = {}
    name = pick(row, '基金簡稱', '公司名稱', 'Name', 'CompanyName') or code
    if category=='fund':
        # 商品明文描述才能分類；不以00開頭猜ETF，不把ETN/REIT當ETF。
        description = str(row.get('基金類型', ''))
        english = str(row.get('基金英文名稱',''))
        is_etf = ('ETF' in description.upper() or '交易所交易基金' in description or
                  '指數股票型基金' in description or bool(re.search(r'\bETF\b',english,re.I)))
        if is_etf and '連結' not in description and 'ETN' not in description.upper():
            fields['kind'] = {**meta, 'value': 'ETF'}
        fields['fund_type'] = {**meta, 'value': description}
    else:
        if not re.fullmatch(r'\d{4}', code): return None
        fields['kind'] = {**meta, 'value': 'STOCK'}
    if category=='eps':
        try:
            year = int(pick(row, '年度', 'Year')); year += 1911 if year<1911 else 0
            quarter = int(pick(row, '季別', 'Season'))
            if quarter not in (1,2,3,4) or not 2000<=year<=local_now().date().year: return None
        except (ValueError, TypeError): return None
        value = numeric(row.get('基本每股盈餘（元）'))
        if value is not None:
            fields['eps'] = {**meta, 'value': value, 'period': f'{year}Q{quarter}',
                             'basis': '財報年初至本季累計；非近四季EPS'}
    elif category=='valuation':
        pe = numeric(pick(row, 'PEratio', 'PriceEarningRatio'))
        dy = numeric(pick(row, 'DividendYield', 'YieldRatio'))
        if pe is not None and pe>0: fields['pe'] = {**meta, 'value': pe}
        # 官方殖利率口徑獨立顯示，不冒充近一年實際配息率。
        if dy is not None and dy>=0: fields['official_yield'] = {**meta, 'value': dy,
            'basis': '交易所公告殖利率；不等同近一年已發配息／目前價格'}
    elif category=='roe_report':
        value = numeric(pick(row, '股東權益報酬率(%)', '股東權益報酬率'))
        if value is not None:
            fields['reported_roe'] = {**meta, 'value': value/100,
                'basis': '董事酬金報表所列ROE；來源未提供明確財報期間，僅展示不參與篩選'}
    return code, {'name': name, 'fields': fields}


def merge(market, rows, category, source, now):
    key = 'fundamentals:index:'+market
    index = get(key, {})
    count = 0
    for row in rows:
        parsed = parse(row,market,category,source,now)
        if parsed is None: continue
        code, entry = parsed
        existing = index.setdefault(code, {'name': entry['name'], 'fields': {}})
        for field, value in entry['fields'].items():
            old = existing['fields'].get(field, {})
            if field=='kind' and old.get('value')=='ETF' and category!='fund': continue
            if (value.get('period',''),value['as_of']) >= (old.get('period',''),old.get('as_of','')):
                existing['fields'][field] = value
                existing['name'] = entry['name']
        count += 1
    if count: put(key,index)
    return count


def attach(data):
    symbol = data['symbol']; code,market = symbol.rsplit('.',1)
    entry = get('fundamentals:index:'+market,{}).get(code,{})
    fields = entry.get('fields',{})
    data['fundamentals_version'] = VERSION
    data['fundamental_details'] = fields
    if fields.get('kind'): data['kind'] = fields['kind']['value']
    if entry.get('name'): data['name'] = entry['name']
    today = local_now().date()
    for name in ('eps','pe'):
        data[name] = None
        record = fields.get(name)
        if record and 0 <= (today-date.fromisoformat(record['as_of'])).days <= (180 if name=='eps' else 14):
            data[name] = record['value']
    # ROE報表期間不明、年配息與總費用缺資料，仍維持None，不推估。
    missing = [label for key,label in [('eps','EPS'),('roe','可核對期間的ROE'),
               ('yield','近一年已發現金配息率')] if data.get(key) is None]
    if data['kind']=='ETF': missing=['年度總費用率','近一年已發現金配息率']
    data['warnings'] = [w for w in data.get('warnings',[]) if '此來源尚未整合' not in w]
    if data['kind']!='UNKNOWN':
        data['warnings']=[w for w in data['warnings'] if 'UNKNOWN' not in w]
    data['warnings'] = [w for w in data['warnings'] if not w.startswith('基本面尚缺：')]
    if missing: data['warnings'].append('基本面尚缺：'+'、'.join(missing)+'；缺項不判定符合。')
    return data
