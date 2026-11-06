from datetime import datetime,timezone
from unittest.mock import Mock
import pytest
from app.services import freshness
from app.db import put,get
from app.providers import taiwan_official as official

NOW=datetime(2026,11,6,18,17,tzinfo=freshness.TAIPEI)

def test_before_evening_does_not_force_refresh():
    before=NOW.replace(hour=14)
    assert not freshness.needs_evening_refresh(0,'2026-11-05',before)

def test_evening_invalidates_pre_evening_yesterday_quote():
    assert freshness.needs_evening_refresh(NOW.replace(hour=17).timestamp(),'2026-11-05',NOW)
    assert not freshness.needs_evening_refresh(NOW.replace(hour=18,minute=1).timestamp(),'2026-11-05',NOW)

def test_today_quote_and_weekends_do_not_force_refresh():
    assert not freshness.needs_evening_refresh(0,'2026-11-06',NOW)
    assert not freshness.needs_evening_refresh(0,'2026-11-06',NOW.replace(day=7))

def test_display_retains_actual_quote_date():
    note=freshness.quote_note({'symbol':'2330.TW','date':'2026-11-05'},NOW)
    assert '尚未取得今日行情' in note
    assert freshness.quote_note({'symbol':'2330.TW','date':'2026-11-06'},NOW)=='今日盤後行情。'

def test_update_time_converts_utc_to_taipei():
    assert freshness.format_updated_at('2026-11-06T10:20:00+00:00')=='2026/11/06 18:20（台灣）'

def test_evening_snapshot_cache_refreshes_once(monkeypatch):
    monkeypatch.setattr(freshness,'local_now',lambda:NOW)
    put('official:snapshot:TW',{'at':NOW.replace(hour=17).timestamp(),'data':{'2330':{'date':'2026-11-05'}}})
    load=Mock(return_value={'2330':{'date':'2026-11-06'}})
    # 時間軸與快取clock一致；二次讀取不會重打相同來源。
    monkeypatch.setattr(official.time,'time',lambda:NOW.timestamp())
    assert official.cached('snapshot:TW',7200,load)['2330']['date']=='2026-11-06'
    official.cached('snapshot:TW',7200,load)
    assert load.call_count==1

def test_line_message_labels_both_dates():
    from app.channels.commands import format_quote
    d={'name':'台積電','symbol':'2330.TW','price':2240,'currency':'TWD','date':'2026-11-05','updated_at':'2026-11-06T10:20:00+00:00','income':{'score':0,'total':1},'swing':{'score':1,'total':3}}
    text=format_quote(d)
    assert '行情日 2026-11-05' in text and '更新時間 2026/11/06 18:20' in text
