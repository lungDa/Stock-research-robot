"""常用中文問法＋精確別名，不臆測股票、不在Webhook下載行情。"""
import re,unicodedata
from app.providers.market import normalize
from app.services.watchlist import add,remove,watches,toggle,subscribed
from app.services.research import cached_quote
from app.services.accounts import can_use_personal
from app.services.multifactor import rated,settings_for,rated_many
from app.services import assistant
from app.db import get
from app.services.freshness import format_updated_at,quote_note
from app.channels.assistant_menu import menu,quick_reply,app_url
HELP='完整功能：查詢股票、追蹤/取消追蹤、我的清單、我的分級、今日重點、存股選股、波段選股、資料狀態、通知設定/開關、盤後摘要開關、只看重要訊號、LINE綁定、個人規則、修改密碼、匯入年度資料。輸入「功能選單」可用按鈕操作。'
ALIASES={'台積電':'2330.TW','中華電':'2412.TW','中華電信':'2412.TW','鴻海':'2317.TW','台達電':'2308.TW','聯發科':'2454.TW','元大台灣50':'0050.TW','元大台灣五十':'0050.TW','元大高股息':'0056.TW','國泰永續高股息':'00878.TW','富邦台50':'006208.TW'}
PRIVATE={'追蹤','取消追蹤','我的清單','我的分級','通知開啟','通知關閉','通知設定','盤後摘要開啟','盤後摘要關閉','只看重要訊號'}


def resolve(value):
    value=unicodedata.normalize('NFKC',value).strip().replace('臺','台')
    if re.fullmatch(r'(?:\d{4,6}[A-Z]?(?:\.(?:TW|TWO))?|[A-Za-z][A-Za-z.\-]{0,14})',value,re.I):return value.upper()
    if value in ALIASES:return ALIASES[value]
    matches=set()
    for market in ('TW','TWO'):
        for key in ('official:catalog:','official:snapshot:','fundamentals:index:'):
            record=get(key+market,{})
            for code,row in record.get('data',record).items():
                if isinstance(row,dict) and str(row.get('name','')).replace('臺','台')==value and code!='_meta':matches.add(code+'.'+market)
    if len(matches)==1:return next(iter(matches))
    if len(matches)>1:raise ValueError('名稱對應多個標的，請指定代號：'+'、'.join(sorted(matches)))
    raise ValueError('尚無法確認這個名稱，請提供股票代號，例如2330或6488.TWO。')


def parse(text):
    t=unicodedata.normalize('NFKC',text).strip()
    short=re.sub(r'\s+','',t)
    synonyms={'選單':'功能選單','全部功能':'功能選單','功能':'功能選單','幫助':'功能選單','help':'功能選單','開始使用':'功能選單',
       '我的追蹤':'我的清單','追蹤清單':'我的清單','我的自選':'我的清單','看我的清單':'我的清單',
       '今天有什麼值得看':'今日重點','今天有什麼值得看?':'今日重點','今天看什麼':'今日重點','今天重點':'今日重點','盤後重點':'今日重點',
       '綁定LINE':'綁定','綁定line':'綁定','我要綁定':'綁定','登入':'綁定','設定':'個人設定',
       '開啟通知':'通知開啟','關閉通知':'通知關閉','不要通知':'通知關閉','暫停通知':'通知關閉','通知狀態':'通知設定',
       '只通知重要訊號':'只看重要訊號','開啟盤後摘要':'盤後摘要開啟','關閉盤後摘要':'盤後摘要關閉'}
    if short in synonyms:return synonyms[short],''
    known={'功能選單','我的清單','我的分級','今日重點','綁定','個人設定','修改密碼','歷史資料','使用說明','通知設定','通知開啟','通知關閉','盤後摘要開啟','盤後摘要關閉','只看重要訊號','資料狀態','存股選股','波段選股','查詢','追蹤','取消追蹤'}
    if short in known:return short,''
    patterns=[('取消追蹤',r'^(?:請|幫我|我想)?(?:取消追蹤|移除追蹤|移除)\s*(.+?)[。!！]?$'),
              ('追蹤',r'^(?:請|幫我|我想)?(?:新增追蹤|加入追蹤|追蹤)\s*(.+?)[。!！]?$'),
              ('查詢',r'^(?:請|幫我|我想)?(?:查詢|分析|查一下|看看|查)\s*(.+?)[。!！]?$')]
    for command,pattern in patterns:
        found=re.fullmatch(pattern,t)
        if found:return command,found[1].strip()
    if re.fullmatch(r'(?:\d{4,6}[A-Za-z]?(?:\.(?:TW|TWO))?|[A-Z]{1,6})',short,re.I) or short.replace('臺','台') in ALIASES:return '查詢',short
    return '未知',''


def login_help():
    return '請先到股海燈塔網站，點「使用LINE登入個人功能」，以你自己的LINE完成綁定。首次輸入0000，再改成8位數字密碼；之後清單與設定會各自保存。'+('\n'+app_url() if app_url() else '\n管理者尚未設定PUBLIC_APP_URL。')


def format_quote(d):
    r=d.get('rating',{})
    return (f"{d['name']}（{assistant.display_symbol(d['symbol'])}）\n行情日 {d['date']}｜{d['currency']} {d['price']:.2f}\n"
        f"更新時間 {format_updated_at(d.get('updated_at'))}\n{quote_note(d)}\n"
        f"分級 {r.get('grade','尚未評估')}｜資料完整度 {r.get('coverage',0)}%\n"
        f"存股 {d['income']['score']}/{d['income']['total']}；波段 {d['swing']['score']}/{d['swing']['total']}\n"
        '可輸入「追蹤＋代號」，或點下方功能選單。規則篩選非報酬預測。')


def handle(user,text):
    command,arg=parse(text)
    personal=can_use_personal(user)
    if command in PRIVATE and not personal:return login_help()
    if command in ('綁定','個人設定','修改密碼','歷史資料'):
        if command=='綁定':return login_help() if not personal else '你已完成LINE綁定與初始密碼設定。可查看我的清單或開啟個人設定。'+('\n'+app_url() if app_url() else '')
        return {'個人設定':'到網站「評分與通知設定」調整門檻、期間、權重與通知需求。','修改密碼':'到網站「評分與通知設定」最下方修改密碼；需要目前密碼，新密碼為8位數字。','歷史資料':'到網站「評分與通知設定」下載CSV範本並匯入核對過的年度資料。'}[command]+('\n'+app_url() if app_url() else '\n網站網址尚未設定。')
    if command in ('追蹤','取消追蹤'):
        if not arg:return '請說「幫我追蹤台積電」或「取消追蹤2330」。新增追蹤不會自動開啟通知。'
        symbol=resolve(arg)
        if command=='追蹤':symbol=add(user,symbol);return '已追蹤 '+assistant.display_symbol(symbol)+'。下一次排程會輪流檢查；可說「我的清單」或「通知開啟」。'
        remove(user,symbol);return '已取消追蹤 '+assistant.display_symbol(normalize(symbol))
    if command=='我的清單':
        rows=watches(user)
        return '我的追蹤清單：\n'+'\n'.join(assistant.display_symbol(x) for x in rows)+'\n可說「我的分級」查看。' if rows else '你的清單還是空的。先說「幫我追蹤台積電」或「追蹤00878」，再設定個人條件。'
    if command in ('我的分級','今日重點'):
        if personal:return assistant.summary(user)
        report=get('scan:latest',{});items=rated_many(report.get('candidates',[])[:30],'public')
        rows=[d for d in items if d['rating']['grade'] in ('買','強力買')]
        return '公開市場批次重點（預設規則，非全市場）：\n'+('\n'.join(d['name']+'｜'+assistant.display_symbol(d['symbol'])+'：'+d['rating']['grade'] for d in rows[:3]) or '本批沒有資料完整且符合買入級別的標的；不代表全市場沒有機會。')+'\nLINE綁定後可看自己的追蹤重點。'
    if command=='通知設定':
        c=settings_for(user);p=assistant.preferences(user)
        return f"通知：{'開啟' if user in subscribed() else '關閉'}\n每日最多{c['daily_cap']}則，單檔升降級優先。\n盤後摘要：{'開' if p['daily_brief'] else '關'}；空清單提醒：{'開' if p['empty_reminder'] else '關'}（最多7天一次）。\n可說「只看重要訊號」「盤後摘要開啟」或「通知關閉」。"
    if command in ('通知開啟','通知關閉'):
        toggle(user,command=='通知開啟')
        return command+'。升降級單檔訊息與盤後助理共用每日上限；可說「通知設定」確認。'
    if command in ('只看重要訊號','盤後摘要開啟','盤後摘要關閉'):
        p=assistant.preferences(user)
        if command=='只看重要訊號':p.update(daily_brief=False,empty_reminder=False);toggle(user,True)
        else:p['daily_brief']=command=='盤後摘要開啟'
        if command=='盤後摘要開啟':toggle(user,True)
        assistant.save(user,p)
        return '已更新助理設定。輸入「通知設定」查看；無升降級時，重要訊號模式不會推播。'
    if command=='查詢':
        if not arg:return '可以直接輸入「2330」「查詢00878」或「幫我分析台積電」。上櫃請指定例如6488.TWO。'
        data=cached_quote(resolve(arg))
        if data:return format_quote(rated(data,user if personal else 'public'))
        return '這檔尚無行情快取。可到網頁先查詢，或綁定後加入追蹤等待排程；LINE對話不會臨時大量下載。'+('\n'+app_url() if app_url() else '')
    if command=='資料狀態':
        r=get('scan:latest',{})
        return f"最近批次更新：{format_updated_at(r.get('updated_at'))}\n涵蓋{r.get('fresh_count',0)}/{r.get('universe_size',0)}檔（本批次，非全市場）；實際行情日：{'、'.join(r.get('data_dates',[])) or '尚無資料'}。\n5～10年財報、ETF年度總費用及完整配息仍可能缺資料；缺資料不冒稱符合。"
    if command in ('存股選股','波段選股'):
        report=get('scan:latest',{});key='income' if command=='存股選股' else 'swing'
        if key=='income':
            items=rated_many(report.get('candidates',[])[:30],user if personal else 'public')
            rows=[d['name']+'｜'+assistant.display_symbol(d['symbol'])+'：'+d['rating']['grade'] for d in items if d['rating']['grade'] in ('買','強力買')]
        else:rows=[s.replace('.TWO','／上櫃').replace('.TW','／上市') for s in report.get(key,[])]
        return command+'｜最近批次，非全市場\n更新 '+format_updated_at(report.get('updated_at'))+'\n'+('\n'.join(rows[:5]) or '本批沒有可確認符合的標的；請查看資料完整度。')
    if command=='使用說明':return HELP+'\n可說「幫我追蹤台積電」「今天有什麼值得看」「不要通知」。不需要輸入嚴格格式；目前支援常用問法，不是任意問答AI。'
    if command=='功能選單':return HELP
    return '我還不能確認你的意思。可說「幫我追蹤台積電」「今天有什麼值得看」，或點「全部功能」查看所有操作。'


def respond(user,text):
    command,_=parse(text)
    if command=='功能選單':return menu()
    try:result=handle(user,text)
    except ValueError as e:result=str(e)
    return {'type':'text','text':result[:4900],'quickReply':quick_reply()}
