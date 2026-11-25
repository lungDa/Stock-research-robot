from datetime import datetime
from app.services.freshness import TAIPEI
from jobs import recommend, watch_digest


def test_catch_up_only_within_current_slot(monkeypatch):
    monkeypatch.setattr(recommend, 'init_db', lambda: None)
    monkeypatch.setattr(recommend, 'is_session', lambda day: False)
    now = datetime(2026, 11, 25, 15, 0, tzinfo=TAIPEI)
    assert recommend.run('morning', False, now)['status'] == 'outside_send_window'
    assert recommend.run('morning', False, now, catch_up=True)['status'] == 'closed'
    assert recommend.run('evening', False, now, catch_up=True)['status'] == 'outside_send_window'
    now = now.replace(hour=23)
    assert recommend.run('morning', False, now, catch_up=True)['status'] == 'outside_send_window'
    assert recommend.run('evening', False, now, catch_up=True)['status'] == 'closed'


def test_watch_report_includes_prices_changes_and_missing(monkeypatch):
    monkeypatch.setattr(watch_digest.assistant, 'personal_ratings', lambda user: [
        {'symbol': '2412.TW', 'name': '中華電', 'currency': 'TWD',
         'price': 105, 'date': '2026-11-25', 'rating': {'grade': '觀望'},
         'history': [{'date': '2026-11-24', 'close': 100},
                     {'date': '2026-11-25', 'close': 105}]}
    ])
    message = watch_digest.report('user', '2026-11-25', ['2412.TW', '2330.TW'])
    assert '105.00' in message
    assert '+5.00%' in message
    assert '觀望' in message
    assert '2330.TW｜行情不足' in message
