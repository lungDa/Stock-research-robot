"""掃描母體由 CSV 明確管理，防止把示範清單冒稱全市場。"""
import csv
from app.providers.market import normalize

def load(path='data/universe.csv'):
    with open(path,encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    return list(dict.fromkeys(normalize(r['symbol']) for r in rows if r.get('symbol')))
