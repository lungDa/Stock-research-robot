"""個人歷史資料匯入；明示人工資料，不能把季度EPS當完整年度。"""
import csv,io,math
from urllib.parse import urlparse
from app.db import put
from app.providers.market import normalize
from app.services.freshness import local_now

FIELDS=['year','eps','roe_pct','cash_yield_pct','cash_dividend_per_share',
        'operating_cash_flow','capital_expenditure','cash_dividends_paid','revenue','source_url']

def import_csv(user,symbol,text):
    symbol=normalize(symbol)
    if len(text.encode('utf-8'))>131072:raise ValueError('CSV不得超過128KiB')
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if not reader.fieldnames or set(reader.fieldnames)!=set(FIELDS):raise ValueError('CSV欄位需與範本相同')
    rows={};today=local_now().date()
    for i,row in enumerate(reader):
        if i>=15:raise ValueError('每檔最多15年')
        try:year=int(row['year'])
        except (TypeError,ValueError):raise ValueError('年度須為西元整數')
        if not today.year-16<=year<today.year or str(year) in rows:raise ValueError('年度重複、未結束或超出16年範圍')
        url=urlparse(row['source_url'].strip())
        if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError('每年須附HTTPS來源網址')
        entry={'source_url':row['source_url'].strip(),'provenance':'user_import','as_of':today.isoformat()}
        for name in FIELDS[1:-1]:
            raw=(row.get(name) or '').strip()
            if not raw:continue
            try:value=float(raw)
            except ValueError:raise ValueError('數值格式錯誤：'+name)
            if not math.isfinite(value):raise ValueError('不可使用NaN或無限大')
            if name not in ('eps','roe_pct','operating_cash_flow') and value<0:raise ValueError(name+'不可為負數')
            entry[name]=value
        rows[str(year)]=entry
    if not rows:raise ValueError('CSV沒有資料列')
    # 驗證整份後才取代該使用者這一檔；不覆蓋別人的資料。
    put('annual:'+user+':'+symbol,rows)
    return {'symbol':symbol,'years':sorted(rows),'provenance':'user_import'}
