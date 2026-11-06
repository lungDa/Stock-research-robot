"""完整功能卡片與快捷按鈕；無需下載資料或呼叫生成式AI。"""
from urllib.parse import urlparse
from app.config import settings

def app_url():
    value=settings.public_app_url.strip()
    return value if urlparse(value).scheme=='https' and urlparse(value).hostname else None

def action(label,text=None,web=False):
    if web and app_url():return {'type':'uri','label':label[:20],'uri':app_url()}
    return {'type':'message','label':label[:20],'text':text or label}

GROUPS=[('查詢與追蹤', [('查詢股票','查詢'),('新增追蹤','追蹤'),('取消追蹤','取消追蹤'),('我的清單','我的清單'),('我的分級','我的分級'),('今日重點','今日重點')]),
 ('選股與通知',[('存股選股','存股選股'),('波段選股','波段選股'),('資料狀態','資料狀態'),('通知設定','通知設定'),('開啟全部通知','通知開啟'),('關閉全部通知','通知關閉'),('只看重要訊號','只看重要訊號')]),
 ('帳戶與個人需求',[('LINE綁定','綁定'),('個人規則設定','個人設定'),('修改個人密碼','修改密碼'),('匯入年度資料','歷史資料'),('開啟盤後摘要','盤後摘要開啟'),('關閉盤後摘要','盤後摘要關閉'),('使用說明','使用說明')])]
WEB={'個人設定','修改密碼','歷史資料'}

def menu():
    bubbles=[]
    for title,items in GROUPS:
        content=[{'type':'text','text':title,'weight':'bold','size':'lg','color':'#123B50'},
            {'type':'text','text':'左右滑動查看全部功能；個人功能需先LINE綁定並改密碼。','wrap':True,'size':'xs','color':'#687983'}]
        content += [{'type':'button','height':'sm','style':'link','action':action(label,cmd,cmd in WEB)} for label,cmd in items]
        bubbles.append({'type':'bubble','size':'mega','body':{'type':'box','layout':'vertical','spacing':'sm','contents':content}})
    return {'type':'flex','altText':'股海燈塔完整功能：查詢、追蹤、分級、選股、通知、綁定與個人設定',
            'contents':{'type':'carousel','contents':bubbles}}

def quick_reply():
    items=[('全部功能','功能選單'),('今日重點','今日重點'),('我的清單','我的清單'),('我的分級','我的分級'),
        ('查台積電','查詢 2330'),('通知設定','通知設定'),('LINE綁定','綁定')]
    return {'items':[{'type':'action','action':action(label,text)} for label,text in items]+
        ([{'type':'action','action':action('個人設定','個人設定',True)}] if app_url() else [])}
