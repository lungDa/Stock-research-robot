import base64,hashlib,hmac
import requests
from app.config import settings

def verify(body,signature):
    expected=base64.b64encode(hmac.new(settings.line_secret.encode(),body,hashlib.sha256).digest()).decode()
    return bool(settings.line_secret) and hmac.compare_digest(expected,signature)

def send(endpoint,payload,retry_key=None):
    if not settings.line_token: raise RuntimeError('LINE token 未設定')
    headers={'Authorization':'Bearer '+settings.line_token}
    if retry_key: headers['X-Line-Retry-Key']=retry_key
    r=requests.post('https://api.line.me/v2/bot/message/'+endpoint,json=payload,headers=headers,timeout=(2,4))
    accepted_id = r.headers.get('x-line-accepted-request-id')
    if not (retry_key and r.status_code==409 and accepted_id):
        r.raise_for_status()
    if r.status_code not in (200,409):
        raise RuntimeError('Unexpected LINE response status')
    return {'http_status':r.status_code,'request_id':r.headers.get('x-line-request-id'),
            'accepted_request_id':accepted_id,'delivery_status':'api_accepted_only'}

def reply(token,text):
    message={'type':'text','text':text[:4900]} if isinstance(text,str) else text
    send('reply',{'replyToken':token,'messages':[message]})
def push(user,text,key): return send('push',{'to':user,'messages':[{'type':'text','text':text[:4900]}]},key)
def push_message(user,message,key):
    """Push one immutable LINE message object using the existing retry-key path."""
    if not isinstance(message,dict) or message.get('type') not in ('text','flex'):
        raise ValueError('不支援的 LINE 訊息格式')
    return send('push',{'to':user,'messages':[message]},key)

def quota():
    headers={'Authorization':'Bearer '+settings.line_token}
    base='https://api.line.me/v2/bot/message/'
    a=requests.get(base+'quota',headers=headers,timeout=(2,4)); a.raise_for_status()
    b=requests.get(base+'quota/consumption',headers=headers,timeout=(2,4)); b.raise_for_status()
    limit=a.json().get('value',0)
    return max(0,limit-b.json().get('totalUsage',0)) if a.json().get('type')=='limited' else 0
