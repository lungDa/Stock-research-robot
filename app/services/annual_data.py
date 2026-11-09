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


def supplement(user,symbol,body):
    """Merge only two user-verified annual fields; blank cells never erase data."""
    from app.db import get
    from copy import deepcopy
    symbol=normalize(symbol)
    if not symbol.endswith(('.TW','.TWO')):raise ValueError('此補登介面限台股；其他市場請用年度CSV')
    if not isinstance(body,dict) or body.get('confirmed') is not True:raise ValueError('請先核對公司、完整年度、合併範圍與來源')
    units={'TWD':1,'TWD_THOUSAND':1000,'TWD_MILLION':1000000}
    if body.get('unit') not in units:raise ValueError('請選擇現金股利支出單位')
    rows=body.get('rows')
    if not isinstance(rows,list) or not 1<=len(rows)<=15:raise ValueError('每次補登1至15個年度')
    today=local_now().date();seen=set();validated=[]
    for r in rows:
        if not isinstance(r,dict) or set(r)-{'year','eps','cash_dividends_paid','source_url'}:raise ValueError('年度欄位格式錯誤')
        year=r.get('year')
        if type(year) is not int or not today.year-16<=year<today.year or year in seen:raise ValueError('年度重複、尚未結束或超出16年範圍')
        seen.add(year)
        source=r.get('source_url','')
        if not isinstance(source,str) or len(source)>2048:raise ValueError('來源網址格式錯誤')
        source=source.strip();url=urlparse(source)
        if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError('每年度須附HTTPS官方年報／財報來源網址')
        values={}
        for key in ('eps','cash_dividends_paid'):
            v=r.get(key)
            if v is None:continue
            if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('補登數值須為有限數字；空白請留空')
            if key=='cash_dividends_paid':
                if v<0:raise ValueError('現金股利支出請填正數支出；不可填每股股利')
                v*=units[body['unit']]
            if not math.isfinite(v):raise ValueError('數值超出範圍')
            values[key]=v
        if not values:raise ValueError('每年度至少補登一項數值')
        validated.append((str(year),values,source))
    stored=deepcopy(get('annual:'+user+':'+symbol,{}))
    for year,values,source in validated:
        entry=stored.setdefault(year,{})
        field_sources=entry.setdefault('field_sources',{})
        for key in ('eps','cash_dividends_paid'):
            if key in entry and key not in field_sources:
                field_sources[key]={'url':entry.get('source_url',''),'provenance':entry.get('provenance','user_import'),
                    'as_of':entry.get('as_of',''),'unit':'TWD_PER_SHARE' if key=='eps' else 'TWD'}
        entry.update(values)
        entry.update(source_url=source,provenance='user_report_verified',as_of=today.isoformat(),currency='TWD')
        entry['notes']=['使用者依官方年報核對補登；系統未自動驗證報表內容']
        for key in values:
            field_sources[key]={'url':source,'provenance':'user_report_verified','as_of':today.isoformat(),
                'basis':'reported_full_year_basic_EPS' if key=='eps' else 'reported_full_year_paid_cash_flow',
                'original_unit':'TWD_PER_SHARE' if key=='eps' else body['unit'],'unit':'TWD_PER_SHARE' if key=='eps' else 'TWD'}
    # Atomic application only after every supplied row passed validation.
    put('annual:'+user+':'+symbol,stored)
    return {'symbol':symbol,'years':[y for y,_,_ in validated],'updated_fields':sum(len(v) for _,v,_ in validated),
            'provenance':'user_report_verified'}


def supplemental_rows(user,symbol):
    from app.db import get
    symbol=normalize(symbol)
    data=get('annual:'+user+':'+symbol,{})
    return {'symbol':symbol,'rows':[{'year':int(y),'eps':r.get('eps'),
        'cash_dividends_paid':r.get('cash_dividends_paid'),'source_url':r.get('source_url',''),
        'field_sources':r.get('field_sources',{})} for y,r in sorted(data.items(),reverse=True)]}


def save_ttm_eps(user,symbol,body):
    from datetime import date
    symbol=normalize(symbol)
    if not isinstance(body,dict) or body.get('confirmed') is not True:raise ValueError('請核對近四季EPS及股數基準')
    try:start=date.fromisoformat(body['period_start']);end=date.fromisoformat(body['period_end'])
    except (KeyError,ValueError,TypeError):raise ValueError('請提供TTM起訖日期')
    if not 330<=(end-start).days<=400 or not 0<=(local_now().date()-end).days<=190:raise ValueError('TTM須涵蓋近一年，期末不可在未來或距今超過190天')
    value=body.get('value');source=body.get('source','')
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('EPS須為有限數值')
    if not isinstance(source,str):raise ValueError('來源網址須為文字')
    url=urlparse(source)
    if len(source)>2048 or url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError('請提供官方財報HTTPS來源網址')
    row={'value':value,'period_start':str(start),'period_end':str(end),'source':source,
         'basis':'user_verified_TTM_EPS; reported currency per share; system has not verified report',
         'provenance':'user_report_verified','as_of':str(local_now().date())}
    put('ttm:'+user+':'+symbol,row)
    return {'symbol':symbol,**row}
