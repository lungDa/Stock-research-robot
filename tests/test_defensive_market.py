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


def test_fundamental_and_adjusted_trend_screen_requires_complete_data():
    from datetime import date

    end = date(2026, 11, 24)
    closes = pd.bdate_range(end=end, periods=60, tz=TAIPEI)
    history = {'rows': [{'date': date, 'close': 100 + i}
                        for i, date in enumerate(closes.strftime('%Y-%m-%d'))]}
    annual = {str(year): {'eps': 3, 'roe_pct': 20, 'cash_yield_pct': 6,
                          'cash_dividend_per_share': 2, 'cash_dividends_paid': 10,
                          'operating_cash_flow': 40, 'capital_expenditure': 10,
                          'revenue': 100 * 1.1 ** (year - 2016)}
              for year in range(2016, 2026)}
    docs = {'annual:shared:2317.TW': {'rows': annual}}
    assert job.screen_candidate('2317.TW', history, closes, end, docs) == 'passed'
    annual['2025']['eps'] = .5
    assert job.screen_candidate('2317.TW', history, closes, end, docs) == 'failed_rules'
    annual['2025']['field_sources'] = {'eps': {'as_of': '2026-11-25'}}
    assert job.screen_candidate('2317.TW', history, closes, end, docs) == 'missing_data'
    assert job.screen_candidate('2317.TW', {'rows': history['rows'][1:]},
                                closes, end, docs) == 'missing_data'


def test_scheduled_rank_waits_for_close_and_reuses_same_session(monkeypatch):
    from unittest.mock import Mock

    now = datetime(2026, 11, 24, 19, tzinfo=TAIPEI)
    put('recommendations:calendar:2026', {'year': 2026, 'closed': [], 'opened': []})
    rank = Mock(return_value={'state': 'evaluated'})
    monkeypatch.setattr(job, 'run', rank)
    assert job.run_scheduled(now.replace(hour=17))['state'] == 'waiting_for_session_close'
    rank.assert_not_called()
    assert job.run_scheduled(now)['state'] == 'evaluated'
    rank.assert_called_once_with(now, None)
    snapshot = {'state': 'evaluated', 'as_of': '2026-11-24'}
    put(job.SNAPSHOT, {**snapshot, 'periods': {'1': {'combined': {'eligible': 0, 'matched': 0}}}})
    assert job.run_scheduled(now.replace(hour=20))['state'] == 'evaluated'
    put(job.SNAPSHOT, {**snapshot, 'periods': {'1': {'combined': {'eligible': 5, 'matched': 0}}}})
    assert job.run_scheduled(now.replace(hour=21)) == {'state': 'cached', 'as_of': '2026-11-24'}
    assert rank.call_count == 2


def test_scheduled_rank_retries_when_screen_has_missing_data(monkeypatch):
    from unittest.mock import Mock

    now = datetime(2026, 11, 24, 20, tzinfo=TAIPEI)
    put('recommendations:calendar:2026', {'year': 2026, 'closed': [], 'opened': []})
    rank = Mock(return_value={'state': 'evaluated'})
    monkeypatch.setattr(job, 'run', rank)
    snapshot = {'state': 'evaluated', 'as_of': '2026-11-24',
                'periods': {'1': {'combined': {'eligible': 5}}},
                'screened_periods': {'1': {'combined': {'eligible': 0}}}}
    put(job.SNAPSHOT, {**snapshot, 'screen_counts': {'missing_data': 2}})
    assert job.run_scheduled(now)['state'] == 'evaluated'
    put(job.SNAPSHOT, {**snapshot, 'screen_counts': {'missing_data': 0}})
    assert job.run_scheduled(now)['state'] == 'cached'
    rank.assert_called_once_with(now, None)
