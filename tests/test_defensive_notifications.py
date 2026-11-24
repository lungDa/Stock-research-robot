from datetime import datetime, timedelta

from app.db import get, put
from app.services.defensive_notifications import RISK_SNAPSHOT, event, save_preference
from app.services.freshness import TAIPEI
from jobs import notify_defensive as job


def test_transitions_ignore_quiet_risk_and_small_rank_changes():
    previous = {'level': 3, 'alerted_level': 3, 'symbols': ['a', 'b', 'c', 'd']}
    assert event(1, {}, []) is None
    assert event(2, {}, []) == 'first'
    assert event(4, previous, []) == 'escalated'
    assert event(3, previous, ['a', 'b', 'c', 'e']) is None
    assert event(3, previous, ['b', 'a', 'c', 'd']) == 'ranking_changed'
    assert event(0, previous, []) == 'resolved'


def test_worker_preserves_retry_key_and_never_sends_to_opted_out_users(monkeypatch):
    import jobs.recommend as recommend

    now = datetime(2026, 11, 24, 19, tzinfo=TAIPEI)
    stamp = now.isoformat()
    put(RISK_SNAPSHOT, {'verified': True, 'level': 3, 'observed_at': stamp,
                        'ranking_as_of': '2026-11-24'})
    put(job.SNAPSHOT, {'as_of': '2026-11-24', 'screened_periods': {'1': {
        'combined': {'items': [{'symbol': '2317.TW', 'score': .64}]}
    }}})
    save_preference('Ualice', True)
    monkeypatch.setattr(job, 'member_users', lambda: ['Ualice', 'Ubob'])
    monkeypatch.setattr(job, 'quota', lambda: 100)
    calls = []

    def push(user, text, retry_key):
        calls.append((user, text, retry_key))
        if len(calls) == 1:
            raise OSError('response lost')

    monkeypatch.setattr(recommend, 'push', push)
    assert job.run(now=now)['events'] == 1
    assert not calls
    assert job.run(send=True, now=now)['state'] == 'partial'
    assert job.run(send=True, now=now)['events'] == 1
    assert job.run(send=True, now=now)['events'] == 0
    assert calls[0] == calls[1]
    assert calls[0][0] == 'Ualice' and '2317.TW' in calls[0][1]
    assert get('defensive:line:state:Ualice')['alerted_level'] == 3
    assert job.run(send=True, now=now + timedelta(hours=2))['state'] == 'risk_stale'


def test_worker_can_send_a_new_ranking_for_the_same_risk_snapshot(monkeypatch):
    import jobs.recommend as recommend

    now = datetime(2026, 11, 24, 19, tzinfo=TAIPEI)
    put(RISK_SNAPSHOT, {'verified': True, 'level': 3, 'observed_at': now.isoformat(),
                        'ranking_as_of': '2026-11-24'})
    save_preference('Ualice', True)
    monkeypatch.setattr(job, 'member_users', lambda: ['Ualice'])
    monkeypatch.setattr(job, 'quota', lambda: 100)
    calls = []
    monkeypatch.setattr(recommend, 'push', lambda *args: calls.append(args))
    assert job.run(send=True, now=now)['events'] == 1
    assert '目前沒有可用的當期篩選排名' in calls[0][1]
    put(job.SNAPSHOT, {'as_of': '2026-11-24', 'generated_at': now.isoformat(),
                       'screened_periods': {'1': {'combined': {
                           'items': [{'symbol': '2317.TW', 'score': .64}]}}}})
    assert job.run(send=True, now=now)['events'] == 1
    assert '2317.TW' in calls[1][1]
    assert calls[0][2] != calls[1][2]
    assert job.run(send=True, now=now)['events'] == 0
