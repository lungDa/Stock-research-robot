"""小流量台股母體；不下載ISIN巨型HTML或Nasdaq整包名單。"""
import csv
import re
import time
from pathlib import Path
from app.db import init_db, get, put
from app.providers.taiwan_official import snapshot


def build():
    init_db()
    rows = []
    partial = False
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
