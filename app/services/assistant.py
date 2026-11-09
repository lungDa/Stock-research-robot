"""可選盤後摘要與空清單提醒；必須已訂閱，與重要訊號共用每日額度。"""
from app.db import get,put,get_many
from app.services.multifactor import rated_many
from app.services.watchlist import watches
from app.services.freshness import format_updated_at
DEFAULT={'daily_brief':True,'empty_reminder':True}

def preferences(user):return {**DEFAULT,**get('assistant:prefs:'+user,{})}

def save(user,value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT) or any(type(v) is not bool for v in value.values()):raise ValueError('助理設定格式錯誤')
    put('assistant:prefs:'+user,value);return preferences(user)

def display_symbol(symbol):
    if symbol.endswith('.TWO'):return symbol[:-4]+'／上櫃'
    if symbol.endswith('.TW'):return symbol[:-3]+'／上市'
    return symbol

def personal_ratings(user):
    codes=watches(user)[:30]
    from app.services.research import quotes_for
    return rated_many(quotes_for(codes),user)

def summary(user):
    codes=watches(user)
    if not codes:return '你還沒有追蹤標的。可直接說「幫我追蹤台積電」，再到個人設定調整條件。'
    rows=personal_ratings(user)
    if not rows:return f'已追蹤{len(codes)}檔，還沒有行情快取。下一次排程會輪流檢查；也可先到網頁查詢建立快取。'
    order={'強力買':0,'買':1,'觀望':2,'資料不足':3}
    rows.sort(key=lambda x:order.get(x['rating']['grade'],4))
    lines=['我的追蹤重點（快取，非即時）：']
    for d in rows[:3]:
        lines.append(f"{d['name']}｜{display_symbol(d['symbol'])}：{d['rating']['grade']}，完整度{d['rating']['coverage']}%｜行情日{d['date']}"+('（舊快取）' if d.get('data_status')=='stale' else ''))
    missing=sum(d['rating']['grade']=='資料不足' for d in rows)
    if missing:lines.append(f'{missing}檔尚缺部分資料；可在網頁查看缺項或匯入核對過的年度資料。')
    if len(rows)<len(codes):lines.append(f'另有{len(codes)-len(rows)}檔尚未建立行情快取。')
    lines.append('僅規則篩選，非未來報酬預測。')
    return '\n'.join(lines)
