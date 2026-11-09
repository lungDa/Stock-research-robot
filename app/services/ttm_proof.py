"""Auditable TTM EPS arithmetic on explicitly user-verified financial inputs.

This validates arithmetic/periods/units. It does not independently attest that
the reports or restatement evidence supplied by a user are true.
"""
import math
from datetime import date,timedelta
from urllib.parse import urlparse
from app.services.freshness import local_now

MONEY_UNITS={'TWD':1,'TWD_THOUSAND':1000,'TWD_MILLION':1000000}
SHARE_UNITS={'SHARES':1,'THOUSAND_SHARES':1000,'MILLION_SHARES':1000000}


def is_calendar_ttm(start,end):
    if (end.month,end.day) not in ((3,31),(6,30),(9,30),(12,31)):return False
    return start==date(end.year-1,end.month,end.day)+timedelta(days=1)


def official_reference(value):
    if not isinstance(value,str) or not value.strip() or len(value)>2048:raise ValueError('請提供財報或重編股數的HTTPS來源')
    value=value.strip();url=urlparse(value)
    if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError('來源須為不含登入資訊的HTTPS網址')
    return value


def finite(value,label):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError(label+'須為有限數字')
    return float(value)


def calculate(body,today=None):
    today=today or local_now().date()
    if not isinstance(body,dict) or any(body.get(flag) is not True for flag in (
        'confirmed','ordinary_profit_confirmed','share_basis_confirmed')):
        raise ValueError('請確認普通股可分配損益、四季股數已依同一基準調整及來源')
    if body.get('currency')!='TWD':raise ValueError('此計算介面目前限新台幣台股財報')
    money=MONEY_UNITS.get(body.get('money_unit'));shares=SHARE_UNITS.get(body.get('share_unit'))
    if money is None or shares is None:raise ValueError('請指定損益與股數單位')
    source=official_reference(body.get('share_basis_source'))
    try:basis_date=date.fromisoformat(body['share_basis_date'])
    except (KeyError,TypeError,ValueError):raise ValueError('請提供同一股數基準的核對日期')
    rows=body.get('quarters')
    if not isinstance(rows,list) or len(rows)!=4:raise ValueError('必須提供四個連續完整單季，不可用累計季報重疊加總')
    quarters=[]
    for row in rows:
        if not isinstance(row,dict):raise ValueError('季度欄位格式錯誤')
        try:start=date.fromisoformat(row['period_start']);end=date.fromisoformat(row['period_end'])
        except (KeyError,TypeError,ValueError):raise ValueError('季度起訖日期格式錯誤')
        if (end.month,end.day) not in ((3,31),(6,30),(9,30),(12,31)) or start!=date(end.year,end.month-2,1):
            raise ValueError('每列須為一個完整單季，不能填年初至本季累計')
        profit=finite(row.get('ordinary_profit'),'普通股可分配損益')*money
        weighted=finite(row.get('weighted_average_shares'),'加權平均普通股股數')*shares
        if not math.isfinite(profit) or not math.isfinite(weighted) or weighted<=0:raise ValueError('股數須大於0且數值不可超出範圍')
        reported=row.get('reported_basic_eps')
        if reported is not None:
            reported=finite(reported,'單季基本EPS')
            if abs(profit/weighted-reported)>.0051:raise ValueError('單季損益／加權股數與提供的EPS不符，請核對單位及股數基準')
        quarters.append({'period_start':str(start),'period_end':str(end),'days':(end-start).days+1,
            'ordinary_profit_TWD':profit,'weighted_average_shares':weighted,'reported_basic_eps':reported,
            'source':official_reference(row.get('source'))})
    quarters.sort(key=lambda row:row['period_start'])
    for before,after in zip(quarters,quarters[1:]):
        if date.fromisoformat(after['period_start'])!=date.fromisoformat(before['period_end'])+timedelta(days=1):
            raise ValueError('四季必須連續且不可重複或重疊')
    start=date.fromisoformat(quarters[0]['period_start']);end=date.fromisoformat(quarters[-1]['period_end'])
    if not is_calendar_ttm(start,end) or not 0<=(today-end).days<=190:raise ValueError('TTM須為最近可核對的連續12個月，期末距今不得超過190天')
    if not end<=basis_date<=today:raise ValueError('股數基準核對日期須介於TTM期末與今天之間')
    days=sum(row['days'] for row in quarters)
    try:
        weighted=math.fsum(row['weighted_average_shares']*(row['days']/days) for row in quarters)
        profit=math.fsum(row['ordinary_profit_TWD'] for row in quarters)
    except OverflowError:raise ValueError('加總數值超出範圍')
    if not math.isfinite(weighted) or not math.isfinite(profit) or weighted<=0:raise ValueError('加總數值超出範圍')
    value=profit/weighted
    if not math.isfinite(value):raise ValueError('計算結果超出範圍')
    return {'value':value,'period_start':str(start),'period_end':str(end),'source':source,'currency':'TWD',
        'eps_type':'basic','provenance':'user_verified_ttm_components','as_of':str(today),
        'basis':'TTM ordinary-share profit / day-weighted average ordinary shares; common share basis user-verified; reports not independently verified',
        'calculation':{'method':'ordinary_profit_divided_by_day_weighted_shares','quarters':quarters,'days':days,
            'ordinary_profit_TWD':profit,'weighted_average_shares':weighted,
            'share_basis_date':str(basis_date),'share_basis_source':source,
            'arithmetic_verified':True,'source_content_independently_verified':False}}
