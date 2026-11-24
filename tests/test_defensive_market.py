from datetime import datetime

import pandas as pd

from app.db import get, put
from app.services.freshness import TAIPEI
from jobs import rank_defensive_market as job


def test_market_ranker_keeps_gaps_and_uses_audited_universe():
    now = datetime(2026, 11, 24, 19, tzinfo=TAIPEI)
    for year in range(2021, 2027):
        put(f'recommendations:calendar:{year}', {'year': year, 'closed': [], 'opened': []})
    symbols = ['2317.TW', '2330.TW']
    put('v26:universe:verified_symbols', {'verified': True, 'at': now.timestamp(), 'symbols': symbols})
    days = pd.bdate_range(end='2026-11-24', periods=81).strftime('%Y-%m-%d').tolist()
    put('defensive:adjusted:2317.TW', {'as_of': days[-1], 'rows': [
        {'date': day, 'close': 100 + i} for i, day in enumerate(days)
    ]})
    put('defensive:tw_indices', {'rows': {
        day: {'closes': {'tw_electronics': 200 - i}} for i, day in enumerate(days)
    }})
    updates = []
    result = job.run(now, updates.append)
    assert result['coverage'] == {'universe': 2, 'current_history': 1}
    assert result['periods']['1']['tw_electronics']['items'] == [{'symbol': '2317.TW', 'score': 1.}]
    assert result['periods']['1']['combined']['items'] == []
    assert result['benchmark_status']['sox']['state'] == 'benchmark_history_missing'
    assert updates[0]['percent'] == 0 and updates[-1]['percent'] == 100
    assert updates[-1]['qualified_by_period'][1] == 1
    assert get(job.SNAPSHOT) == result
