from app.services.watchlist import add,remove,watches,toggle
from app.services.research import cached_quote
from app.db import get
from app.services.freshness import format_updated_at, quote_note
HELP='查詢 2330｜追蹤 AAPL｜取消追蹤 AAPL｜我的清單｜存股選股｜波段選股｜通知開啟｜通知關閉。上櫃請輸入如 6488.TWO。'
def format_quote(d):
    return (f"{d['name']} ({d['symbol']})\n行情日 {d['date']}｜{d['currency']} {d['price']:.2f}\n"
            f"更新時間 {format_updated_at(d.get('updated_at'))}\n{quote_note(d)}\n"
            f"存股 {d['income']['score']}/{d['income']['total']}；波段 {d['swing']['score']}/{d['swing']['total']}\n"
            '規則篩選參考，詳情請看 Streamlit。')

def handle(user,text):
    parts=text.strip().split(maxsplit=1); command=parts[0] if parts else ''; arg=parts[1] if len(parts)>1 else ''
    if command=='追蹤' and arg: return '已追蹤 '+add(user,arg)+'；待排程更新行情。'
    if command=='取消追蹤' and arg: remove(user,arg); return '已取消追蹤'
    if command=='我的清單': return '自選清單：'+('、'.join(watches(user)) or '尚未設定')
    if command in ('通知開啟','通知關閉'): toggle(user,command=='通知開啟'); return command+'（每天至多一份合併摘要）'
    if command=='查詢' and arg:
        data=cached_quote(arg)
        return format_quote(data) if data else '尚無快取；請至 Streamlit 查詢，或加入追蹤等待排程。'
    if command in ('存股選股','波段選股'):
        report=get('scan:latest',{})
        key='income' if command=='存股選股' else 'swing'
        rows=report.get(key,[])
        return f"資料更新 {report.get('updated_at','尚未掃描')}\n"+('\n'.join(rows[:10]) or '本次沒有符合標的')+'\n完整度請看網頁掃描紀錄。'
    return HELP
