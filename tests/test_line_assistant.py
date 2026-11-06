import json,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from app.api.server import app
from app.channels import commands,line
from app.channels.assistant_menu import menu,GROUPS
from app.services import assistant,proactive
from app.db import get,put
from app.services.watchlist import watches,add
from app.config import settings
from jobs.notify import slot
from tests.test_api import signed

@pytest.mark.parametrize('text,expected',[
 ('幫我追蹤台積電',('追蹤','台積電')),('取消追蹤2330',('取消追蹤','2330')),
 ('幫我分析台積電',('查詢','台積電')),('今天有什麼值得看',('今日重點','')),
 ('我的追蹤',('我的清單','')),('不要通知',('通知關閉','')),('2330',('查詢','2330')),
 ('功能',('功能選單','')),('AAPL',('查詢','AAPL'))])
def test_common_chinese_commands(text,expected):assert commands.parse(text)==expected

def test_actions_and_personal_isolation(monkeypatch):
    commands.handle('Ualice','幫我追蹤台積電')
    assert watches('Ualice')==['2330.TW'] and not watches('Ubob')
    commands.handle('Ualice','取消追蹤台積電');assert not watches('Ualice')
    commands.handle('Ustranger','追蹤2330');assert not watches('Ustranger')
    assert '0000' in commands.handle('Ustranger','綁定')

def test_unknown_and_duplicate_names_not_guessed():
    with pytest.raises(ValueError):commands.resolve('不存在股票名稱')
    put('fundamentals:index:TW',{'1234':{'name':'同名公司'}})
    put('fundamentals:index:TWO',{'5678':{'name':'同名公司'}})
    with pytest.raises(ValueError,match='多個'):commands.resolve('同名公司')

def test_full_menu_contains_all_actions_and_quick_buttons(monkeypatch):
    monkeypatch.setattr(settings,'public_app_url','https://example.com')
    result=commands.respond('Ustranger','功能選單')
    assert result['type']=='flex' and len(result['contents']['contents'])==3
    assert len(json.dumps(result).encode())<30000
    for _,items in GROUPS:
        for label,_ in items:assert label in json.dumps(result,ensure_ascii=False)
    reply=commands.respond('Ualice','我的清單')
    assert len(reply['quickReply']['items'])<=13
    assert '還是空的' in reply['text']

def test_quote_label_not_auto_domain_preview():
    d=dict(name='台積電',symbol='2330.TW',date='2026-11-06',currency='TWD',price=100,
           income={'score':0,'total':4},swing={'score':1,'total':3})
    text=commands.format_quote(d)
    assert '2330.TW' not in text and '2330／上市' in text

def test_follow_welcome_and_binding_available_before_registration(monkeypatch):
    calls=[];monkeypatch.setattr(line,'reply',lambda *args:calls.append(args))
    event={'type':'follow','webhookEventId':'new-follow','replyToken':'reply','source':{'type':'user','userId':'Unew'}}
    body,headers=signed({'events':[event]})
    with TestClient(app) as c:
        assert c.post('/line/webhook',content=body,headers=headers).status_code==200
        assert c.post('/line/webhook',content=body,headers=headers).status_code==200
    assert len(calls)==1 and calls[0][1]['type']=='flex'
    assert not get('member:Unew')

def test_assistant_preferences_private_and_opt_out():
    from tests.test_api import A,B
    with TestClient(app) as c:
        assert c.get('/assistant/preferences').status_code==401
        assert c.put('/assistant/preferences',headers=A,json={'daily_brief':False,'empty_reminder':False}).status_code==200
        assert c.get('/assistant/preferences',headers=B).json()==assistant.DEFAULT
        assert c.put('/assistant/preferences',headers=A,json={'daily_brief':'false','empty_reminder':True}).status_code==400

NOW=datetime(2026,11,6,18,30,tzinfo=ZoneInfo('Asia/Taipei'))

def deliver(monkeypatch,local=NOW,push=None):
    monkeypatch.setattr(proactive.time,'time',lambda:local.timestamp())
    return proactive.nudge('Ualice',local.date().isoformat(),local.timestamp(),100,3,slot,push or (lambda *a:None),time.monotonic()+40,local)

def test_empty_reminder_weekly_and_daily_cap(monkeypatch):
    calls=[];deliver(monkeypatch,push=lambda *a:calls.append(a));deliver(monkeypatch,push=lambda *a:calls.append(a))
    deliver(monkeypatch,NOW+timedelta(days=3),lambda *a:calls.append(a))
    assert len(calls)==1
    assert get('assistant:empty:last:Ualice')['at']==NOW.timestamp()

def test_nudge_before_evening_or_opted_out_not_sent(monkeypatch):
    calls=[];deliver(monkeypatch,NOW.replace(hour=12),lambda *a:calls.append(a))
    assistant.save('Ualice',{'daily_brief':False,'empty_reminder':False})
    deliver(monkeypatch,push=lambda *a:calls.append(a));assert not calls

def test_brief_only_without_signal_and_fresh_report(monkeypatch):
    add('Ualice','2330');calls=[]
    put('scan:latest',{'updated_at':NOW.isoformat()})
    monkeypatch.setattr(assistant,'summary',lambda u:'測試摘要')
    put('signal:state:Ualice:2330.TW',{'sent_at':NOW.timestamp()-60})
    deliver(monkeypatch,push=lambda *a:calls.append(a));assert not calls
    put('signal:state:Ualice:2330.TW',{})
    deliver(monkeypatch,push=lambda *a:calls.append(a));assert len(calls)==1
    assert '盤後助理' in calls[0][1]

def test_nudge_uses_same_daily_slots_as_signal(monkeypatch):
    for _ in range(3):assert slot('Ualice',NOW.date().isoformat(),3)
    calls=[];deliver(monkeypatch,push=lambda *a:calls.append(a));assert not calls

def test_uncertain_nudge_retry_immutable_and_no_next_day_empty_repeat(monkeypatch):
    calls=[]
    def fail(*args):calls.append(args);raise TimeoutError()
    deliver(monkeypatch,push=fail)
    key='assistant:delivery:'+NOW.date().isoformat()+':Ualice'
    state=get(key);state['pending']['last_attempt']-=61;put(key,state)
    deliver(monkeypatch,push=fail)
    assert len(calls)==2 and calls[0]==calls[1]
    deliver(monkeypatch,NOW+timedelta(days=3),fail)
    assert len(calls)==2

def test_menu_publisher_reuses_existing_menu(monkeypatch):
    from jobs import setup_line_menu as publisher
    monkeypatch.setattr(settings,'line_token','test-token')
    remote=[];calls=[]
    def api(method,url,**kw):
        calls.append((method,url))
        if url.endswith('/list'):return {'richmenus':remote}
        if url.endswith('/richmenu'):
            remote.append({'name':kw['json']['name'],'richMenuId':'richmenu-test'})
            return {'richMenuId':'richmenu-test'}
        return {}
    monkeypatch.setattr(publisher,'api',api)
    publisher.publish();publisher.publish()
    assert sum(u.endswith('/richmenu') for _,u in calls)==1
    definition=publisher.definition()
    assert sum(a['bounds']['width']*a['bounds']['height'] for a in definition['areas'])==2500*1686
