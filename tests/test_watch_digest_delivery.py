from datetime import datetime
from contextlib import nullcontext
from unittest.mock import Mock
from app.services.freshness import TAIPEI
from jobs import watch_digest

def test_evening_watch_report_sends_stale_data_with_label_and_deduplicates(monkeypatch):
    day=datetime(2026,11,25,18,17,tzinfo=TAIPEI)
    sent=Mock(return_value=99)
    state={}
    monkeypatch.setattr(watch_digest,'init_db',lambda:None)
    monkeypatch.setattr(watch_digest,'is_session',lambda day:True)
    monkeypatch.setattr(watch_digest,'leased',lambda *a:nullcontext(True))
    monkeypatch.setattr(watch_digest,'subscribed',lambda:['user'])
    monkeypatch.setattr(watch_digest,'can_use_personal',lambda u:True)
    monkeypatch.setattr(watch_digest.assistant,'preferences',lambda u:{'daily_brief':True})
    monkeypatch.setattr(watch_digest,'watches',lambda u:['2330.TW'])
    monkeypatch.setattr(watch_digest.assistant,'personal_ratings',lambda u:[{'symbol':'2330.TW','price':100,'date':'2026-11-24','rating':{'grade':'觀望'}}])
    monkeypatch.setattr(watch_digest,'get',lambda key:state.get(key))
    monkeypatch.setattr(watch_digest,'quota',lambda:100)
    monkeypatch.setattr(watch_digest,'deliver',sent)
    assert watch_digest.run(day.replace(minute=16))['status']=='outside_send_window'
    assert watch_digest.run(day)['messages_sent']==1
    assert '舊行情／待更新' in sent.call_args.args[2][0]
    state[sent.call_args.args[1]]={'messages':[{'sent':True}]}
    assert watch_digest.run(day)['already_sent']==1
    assert sent.call_count==1
