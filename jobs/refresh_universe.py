"""小流量台股母體；不下載ISIN巨型HTML或Nasdaq整包名單。"""
import csv
import os
import re
import time
from pathlib import Path
from app.db import init_db, get, put
from app.providers.taiwan_official import snapshot


def finmind_backup():
    """One optional free master-list request; prefer the latest market per code."""
    token=os.getenv('FINMIND_TOKEN','').strip();now=time.time()
    if not token:return {}
    cached=get('universe:finmind',{})
    if now-cached.get('at',0)<7*86400 and cached.get('markets'):return cached['markets']
    if now<get('universe:finmind_retry',{}).get('next_attempt',0) or now<get('annual:source:finmind',{}).get('next_attempt',0):return {}
    from app.providers.bounded_http import fetch_json
    from app.providers.annual_free import FINMIND,valid_day
    from app.services.data_queue import source_slot
    from app.services.freshness import local_now
    if not source_slot('finmind',100):return {}
    put('universe:finmind_retry',{'next_attempt':now+3600})
    try:
        payload=fetch_json(FINMIND,{'dataset':'TaiwanStockInfo'},headers={'Authorization':'Bearer '+token},max_bytes=1048576,seconds=8)
        if not isinstance(payload,dict) or payload.get('status')!=200:raise ValueError('Invalid stock master')
        rows=payload.get('data')
        if not isinstance(rows,list):raise ValueError('Invalid stock master')
        latest={};conflicts=set()
        for row in rows:
            if not isinstance(row,dict):continue
            code=str(row.get('stock_id',''));day=valid_day(row.get('date'))
            if not re.fullmatch(r'\d{4}|00\d{3,4}[A-Z]?',code) or not day or day>local_now().date():continue
            if code not in latest or str(day)>latest[code]['date']:
                latest[code]=row;conflicts.discard(code)
            elif str(day)==latest[code]['date'] and row.get('type')!=latest[code].get('type'):conflicts.add(code)
        markets={'TW':[],'TWO':[]}
        for code,row in latest.items():
            market={'twse':'TW','tpex':'TWO'}.get(row.get('type'))
            if not market or code in conflicts:continue
            markets[market].append({'symbol':code+'.'+market,'name':str(row.get('stock_name') or code)})
        if not all(markets.values()):raise ValueError('Incomplete stock master markets')
        put('universe:finmind',{'at':now,'markets':markets})
        return markets
    except Exception as exc:
        code=getattr(getattr(exc,'response',None),'status_code',None)
        if code in (401,403,429):put('annual:source:finmind',{'next_attempt':now+86400})
        return {}


def build():
    init_db()
    rows = []
    partial = False
    backup=None
    for market in ('TW', 'TWO'):
        key = 'universe:small:' + market
        prior = get(key)
        ttl = 7 * 86400 if prior and prior.get('complete') else 3600
        if prior and time.time() - prior['at'] < ttl:
            part = prior
        else:
            try:
                quotes = snapshot(market)
                items = []
                for code, quote in quotes.items():
                    # 普通股票與00開頭基金候選；商品正式分類保留至分類模組。
                    if re.fullmatch(r'\d{4}', code) or re.fullmatch(r'00\d{3,4}[A-Z]?', code):
                        items.append({'symbol': code+'.'+market, 'name': quote['name']})
                if not items: raise RuntimeError('沒有可用台股候選')
                complete = quotes.get('_meta', {}).get('complete', True)
                # 新回應只有一部分時，保留較完整的舊清單，不把缺漏標的刪掉。
                if prior and prior.get('complete') and not complete:
                    part = prior
                else:
                    part = {'at':time.time(), 'rows':items, 'complete':complete}
                    put(key, part)
            except Exception as exc:
                if prior:
                    part = prior
                    print(f'{market}母體更新暫不可用，使用舊清單：{type(exc).__name__}')
                else:
                    if backup is None:backup=finmind_backup()
                    if backup.get(market):
                        part={'at':time.time(),'rows':backup[market],'complete':True,'source':'FinMind / TaiwanStockInfo'}
                        put(key,part)
                    else:
                        print(f'{market}母體暫不可用，本次不涵蓋該市場：{type(exc).__name__}')
                        partial = True
                        continue
        rows.extend(part['rows'])
        partial |= not part.get('complete', False)
    if not rows:
        raise RuntimeError('兩個市場都沒有可用母體；停止掃描，不冒用示範清單')
    rows = list({row['symbol']:row for row in rows}.values())
    out = Path('data/universe.csv'); out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['symbol','name']);writer.writeheader();writer.writerows(rows)
    temp.replace(out)
    put('universe:scope', {'partial':partial, 'count':len(rows), 'market':'TW/TWO',
                          'updated_at':time.time()})
    print(f'台股候選母體{len(rows)}檔；部分涵蓋={partial}；美股本階段不主動掃描')

if __name__ == '__main__': build()
