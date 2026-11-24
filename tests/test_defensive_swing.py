from datetime import datetime

import pandas as pd

from app.db import put
from app.services.defensive_notifications import RISK_SNAPSHOT
from app.services.defensive_swing import report, swing_action
from app.services.freshness import TAIPEI


def test_swing_signals_and_hold_advice():
    assert swing_action(110, 105, 100, 3, False) == 'buy'
    assert swing_action(110, 105, 100, 4, False) == 'watch'
    assert swing_action(110, 105, 100, 3, True) == 'hold'
    assert swing_action(104, 105, 100, 3, True) == 'reduce'
    assert swing_action(99, 105, 100, 3, True) == 'exit'


def test_archive_backtest_uses_following_open_and_retains_missing_session_slots():
    now = datetime(2026, 11, 24, 19, tzinfo=TAIPEI)
    for year in range(2021, 2027):
        put(f'recommendations:calendar:{year}', {'year': year, 'closed': [], 'opened': []})
    days = pd.bdate_range(end=now.date(), periods=100).strftime('%Y-%m-%d').tolist()
    rows = [{'date': day, 'close': 100 + i, 'open': 99 + i} for i, day in enumerate(days)]
    rows[73].pop('open')
    put('defensive:adjusted:2317.TW', {'rows': rows})
    day = days[62]
    key = f'{RISK_SNAPSHOT}:session:{day}'
    put(key, {'verified': True, 'level': 3, 'session_date': day,
              'observed_at': day + 'T18:25:00+08:00'})
    result = report('2317.TW', now)
    assert result['verified_risk_sessions'] == 1
    assert result['action'] == 'watch'
    assert result['backtests']['1']['10']['summary']['count'] == 0
    trade = result['backtests']['1']['20']['trades'][0]
    assert trade['entry'].startswith(days[63]) and trade['exit'].startswith(days[83])
    assert trade['holding_sessions'] == 20
    assert result['backtests']['1']['20']['benchmarks']['combined']['count'] == 1


def test_managed_backtest_reduces_once_and_exits_at_next_open():
    from app.services.defensive_model import backtest

    opens = pd.bdate_range(start='2026-11-02', periods=9, tz=TAIPEI) + pd.Timedelta(hours=9)
    prices = pd.Series([99., 100., 105., 120., 130., 125., 110., 115., 116.], index=opens)
    signals = {opens[0] + pd.Timedelta(hours=8): {
        'action': 'buy', 'level': 3, 'benchmark': 'combined'}}
    management = {opens[2] + pd.Timedelta(hours=8): 'reduce',
                  opens[3] + pd.Timedelta(hours=8): 'reduce',
                  opens[5] + pd.Timedelta(hours=8): 'exit'}
    trial = backtest(prices, signals, opens[-1], 1, 10, management=management)
    trade = trial['trades'][0]
    assert trade['entry'] == opens[1].isoformat()
    assert trade['reduction'] == opens[3].isoformat()
    assert trade['exit'] == opens[6].isoformat()
    assert trade['exit_reason'] == 'signal'
    assert trade['holding_sessions'] == 5
    assert abs(trade['return'] - .15) < 1e-9
    assert backtest(prices, signals, opens[5], 1, 10, management=management)['trades'] == []


def test_single_benchmark_uses_only_the_archived_level(monkeypatch):
    from app.services import defensive_swing as service

    now = datetime(2026, 11, 24, 19, tzinfo=TAIPEI)
    closes = pd.bdate_range(end=now.date(), periods=81, tz=TAIPEI)
    dates = closes.strftime('%Y-%m-%d')
    history = {'rows': [{'date': day, 'open': 100 + i, 'close': 101 + i}
                        for i, day in enumerate(dates)]}
    monkeypatch.setattr(service, 'market_context', lambda *args: (
        {'defensive:adjusted:2317.TW': history}, now.date(), closes, {}))
    for day, levels in ((dates[60], {'sox': 2}), (dates[62], {})):
        put(f'{RISK_SNAPSHOT}:session:{day}', {'verified': True, 'level': 4, 'session_date': day,
                                            'observed_at': day + 'T18:25:00+08:00',
                                            'benchmark_levels': levels})
    assert report('2317.TW', now)['entry_signals'] == 0
    result = report('2317.TW', now, benchmark='sox')
    assert result['verified_risk_sessions'] == 1
    assert result['backtests']['1']['10']['benchmarks']['sox']['count'] == 1
    assert report('2330.TW', now, benchmark='2330.TW')['state'] == 'self_benchmark'
