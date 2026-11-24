"""Exercise the close-to-LINE path with stored data and a simulated LINE transport."""
from datetime import datetime

import pandas as pd

from app.db import get, put
from app.services.defensive_notifications import RISK_SNAPSHOT, save_preference
from app.services.freshness import TAIPEI
from jobs import monitor_defensive_risk, notify_defensive, rank_defensive_market, recommend


def test_close_pipeline_waits_for_missing_index_then_sends_rank_once(monkeypatch):
    now = datetime(2026, 11, 24, 18, 25, tzinfo=TAIPEI)
    for year in range(2021, 2027):
        put(f'recommendations:calendar:{year}', {'year': year, 'closed': [], 'opened': []})

    days = pd.bdate_range(end=now.date(), periods=85).strftime('%Y-%m-%d').tolist()
    today = days[-1]
    symbol = '2317.TW'
    put('v26:universe:verified_symbols', {'verified': True, 'at': now.timestamp(),
                                        'symbols': [symbol, '2330.TW']})
    for code, prices in ((symbol, [100 + i for i in range(len(days))]),
                         ('2330.TW', [100 * .971 ** i for i in range(len(days))])):
        put('defensive:adjusted:' + code, {'as_of': today, 'rows': [
            {'date': day, 'close': price} for day, price in zip(days, prices)
        ]})
    put('defensive:tw_indices', {'rows': {
        day: {'observed_at': day + 'T18:20:00+08:00',
              'closes': {'tw_electronics': 200 * .971 ** i, 'tw_semiconductors': 300 * .971 ** i}}
        for i, day in enumerate(days)
    }})
    put('annual:shared:' + symbol, {'rows': {
        str(year): {'eps': 3, 'roe_pct': 20, 'cash_yield_pct': 6,
                    'cash_dividend_per_share': 2, 'cash_dividends_paid': 10,
                    'operating_cash_flow': 40, 'capital_expenditure': 10,
                    'revenue': 100 * 1.1 ** (year - 2016)}
        for year in range(2016, 2026)
    }})

    us_days = days[:-1]
    index = {
        'rows': [{'date': day, 'close': 400 * .971 ** i} for i, day in enumerate(us_days)],
        'session_closes': [day + 'T16:00:00-05:00' for day in us_days],
        'published_at': {day: day + 'T17:00:00-05:00' for day in us_days},
    }
    put('defensive:index:nasdaq_100', index)
    save_preference('Ualice', True)
    monkeypatch.setattr(notify_defensive, 'member_users', lambda: ['Ualice'])
    monkeypatch.setattr(notify_defensive, 'quota', lambda: 100)
    sent = []
    monkeypatch.setattr(recommend, 'push', lambda *args: sent.append(args))

    assert monitor_defensive_risk.run(now)['state'] == 'insufficient_data'
    assert notify_defensive.run(send=True, now=now)['state'] == 'risk_unavailable'
    assert not sent
    assert not rank_defensive_market.run_scheduled(now)['screened_periods']['1']['combined']['items']

    put('defensive:index:sox', index)
    assert monitor_defensive_risk.run(now)['level'] == 3
    assert get(f'{RISK_SNAPSHOT}:session:{today}') == get(RISK_SNAPSHOT)
    board = rank_defensive_market.run_scheduled(now)['screened_periods']['1']['combined']
    assert [item['symbol'] for item in board['items']] == [symbol]
    assert notify_defensive.run(send=True, now=now)['events'] == 1
    assert rank_defensive_market.run_scheduled(now)['state'] == 'cached'
    assert notify_defensive.run(send=True, now=now)['events'] == 0
    assert len(sent) == 1 and sent[0][0] == 'Ualice' and symbol in sent[0][1]
