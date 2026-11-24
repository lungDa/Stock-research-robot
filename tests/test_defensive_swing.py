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
