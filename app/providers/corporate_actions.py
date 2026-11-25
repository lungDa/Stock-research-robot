"""Latest-price-anchored Taiwan adjustments using verified free event references.
Readers use persisted data only. Raw closes and volumes are never overwritten.
"""
import math
from datetime import date
from app.providers.date_windows import covers

FEEDS = {
    'TaiwanStockDividendResult': ('before_price', 'after_price'),
    'TaiwanStockSplitPrice': ('before_price', 'after_price'),
    'TaiwanStockParValueChange': ('before_close', 'after_ref_close'),
    'TaiwanStockCapitalReductionReferencePrice': ('ClosingPriceonTheLastTradingDay', 'PostReductionReferencePrice'),
}
BASIS = 'latest_price_adjusted'
CATALOG_FEEDS = ('TaiwanStockSplitPrice', 'TaiwanStockParValueChange')


def request_parameters(feed, symbol, start, end):
    # FinMind documents these two as whole-catalog endpoints.
    if feed == 'TaiwanStockSplitPrice':
        return {'dataset': feed}
    if feed == 'TaiwanStockParValueChange':
        return {'dataset': feed, 'start_date': start}
    return {'dataset': feed, 'data_id': symbol.split('.')[0], 'start_date': start, 'end_date': end}


def positive(value):
    if isinstance(value, bool):raise ValueError('invalid reference price')
    value = float(value)
    if not math.isfinite(value) or value <= 0:raise ValueError('invalid reference price')
    return value


def compact(feed, records, symbol, start, end):
    if not isinstance(records, list):raise ValueError('invalid event response')
    before, after = FEEDS[feed]
    events = {}
    for row in records:
        if not isinstance(row, dict):raise ValueError('invalid event row')
        if str(row.get('stock_id')) != symbol.split('.')[0]:
            # Split and par-value endpoints document a whole-catalog response.
            if feed in ('TaiwanStockSplitPrice','TaiwanStockParValueChange'):continue
            raise ValueError('event company mismatch')
        day = date.fromisoformat(row['date']).isoformat()
        if not start <= day <= end:continue
        event = {'date':day,'before':positive(row[before]),'after':positive(row[after]),'feed':feed}
        if day in events and events[day] != event:raise ValueError('conflicting event references')
        events[day] = event
    return list(events.values())


def adjust(rows, feeds, symbol):
    """Reject incomplete coverage, conflicts and unmatched pre-event closes."""
    rows = sorted(rows, key=lambda r:r['date'])
    if not rows:raise ValueError('沒有可還原的日線')
    start, end = rows[0]['date'], rows[-1]['date']
    if len({r['date'] for r in rows}) != len(rows):raise ValueError('日線日期重複')
    for row in rows:
        date.fromisoformat(row['date']);positive(row['close'])
    events = {}
    for feed in FEEDS:
        state = feeds.get(feed, {})
        if state.get('status') != 'ok' or not covers(state.get('coverage_windows',[]),start,end):
            raise ValueError('公司行動資料尚未涵蓋整段日線')
        for event in state.get('events',[]):
            day = event['date']
            if not start < day <= end:continue
            before, after = positive(event['before']), positive(event['after'])
            factor = after / before
            if not math.isfinite(factor) or factor <= 0:raise ValueError('還原係數無效')
            if day in events:
                old = events[day]
                if not (math.isclose(old['before'],before,abs_tol=.02,rel_tol=1e-6)
                        and math.isclose(old['after'],after,abs_tol=.02,rel_tol=1e-6)):
                    raise ValueError('同日公司行動來源衝突，未重複套用係數')
                continue
            events[day] = {**event,'before':before,'after':after,'factor':factor}
    for day, event in events.items():
        index = next((i for i,r in enumerate(rows) if r['date'] == day),None)
        if not index or not math.isclose(float(rows[index-1]['close']),event['before'],abs_tol=.02,rel_tol=1e-6):
            raise ValueError('事件日期／前收盤價無法與日線核對')
    result = []
    for row in rows:
        factor = math.prod(e['factor'] for day,e in events.items() if row['date'] < day <= end)
        value = positive(row['close']) * factor
        if not math.isfinite(value) or value <= 0:raise ValueError('還原股價無效')
        result.append({**row,'adjusted_close':value,'adjustment_factor':factor})
    return result, list(events.values())


def attach(data, read=None):
    if not data.get('symbol','').endswith(('.TW','.TWO')):return data
    if read is None:
        from app.db import get
        read = get
    result = {**data,'technical_basis':BASIS,'adjustment_status':'missing',
              'ma20':None,'ma60':None,'adjusted_close':None,'volatility':None,
              'adjusted_history':[]}
    try:
        if data.get('technical_history_incomplete'):raise ValueError('歷史日線有缺口，等待月份回補')
        rows = data.get('history',[])
        if not rows or max(r['date'] for r in rows) != data.get('date'):raise ValueError('日線尚未涵蓋行情日')
        latest = max(rows,key=lambda r:r['date'])
        if positive(latest['close']) != positive(data.get('price')):raise ValueError('行情與日線收盤價不符')
        feeds = {f:read('corporate:feed:'+data['symbol']+':'+f,{}) for f in FEEDS}
        adjusted, events = adjust(rows, feeds, data['symbol'])
        values = [r['adjusted_close'] for r in adjusted]
        # Unexplained residual jumps still block technical signals.
        if any(abs(b/a-1) > .30 for a,b in zip(values,values[1:])):raise ValueError('還原後仍有未確認的大幅跳動')
        import pandas as pd
        result.update(adjustment_status='verified',adjustment_reason='公司行動期間與前收盤已核對',
                      adjustment_events=events,adjusted_history=adjusted,adjusted_close=values[-1],
                      adjustment_anchor=data['date'],
                      ma20=sum(values[-20:])/20 if len(values)>=20 else None,
                      ma60=sum(values[-60:])/60 if len(values)>=60 else None,
                      volatility=float(pd.Series(values).pct_change().std()*252**.5*100) if len(values)>=60 else None)
        if any(e['date'] > adjusted[max(0,len(adjusted)-20)]['date'] for e in events):result['volume_ratio']=None
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        result.update(adjustment_reason=str(exc),adjustment_events=[])
    warning = ('技術均線採最新價格基準還原；畫面股價與原始日線保留實際收盤價。' if result['adjustment_status']=='verified'
               else '還原資料未確認：'+result['adjustment_reason']+'；均線與波動暫不判定。')
    warnings=[w for w in data.get('warnings',[]) if not w.startswith(('還原資料未確認：','技術均線採最新價格基準還原'))]
    if result['adjustment_status']=='verified':
        warnings=[w for w in warnings if not w.startswith('歷史價格出現超過30%')]
    result['warnings'] = list(dict.fromkeys(warnings+[warning]))
    return result
