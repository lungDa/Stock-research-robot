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
    if retry_key and r.status_code==409: return  # LINE 已接受相同 retry key
    r.raise_for_status()

def reply(token,text): send('reply',{'replyToken':token,'messages':[{'type':'text','text':text[:4900]}]})
def push(user,text,key): send('push',{'to':user,'messages':[{'type':'text','text':text[:4900]}]},key)
def quota():
    headers={'Authorization':'Bearer '+settings.line_token}
    base='https://api.line.me/v2/bot/message/'
    a=requests.get(base+'quota',headers=headers,timeout=(2,4)); a.raise_for_status()
    b=requests.get(base+'quota/consumption',headers=headers,timeout=(2,4)); b.raise_for_status()
    limit=a.json().get('value',0)
    return max(0,limit-b.json().get('totalUsage',0)) if a.json().get('type')=='limited' else 0
