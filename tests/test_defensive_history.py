from datetime import date, datetime
from unittest.mock import Mock

import pytest

from app.db import get, put
from app.services.freshness import TAIPEI
from jobs import refresh_defensive_history as history


def bar(day, code='2330'):
    return {'date': day, 'stock_id': code, 'open': '100', 'close': '102'}


@pytest.fixture
def stored_calendar():
    for year in range(2020, 2026):
        put(f'recommendations:calendar:{year}', {'year': year, 'closed': [], 'opened': []})


def test_coverage_reports_gaps_and_checks_company(stored_calendar):
    start, end = date(2020, 1, 6), date(2025, 1, 6)
    payload = {'status': 200, 'data': [bar('2025-01-03'), bar('2025-01-06')]}
    result = history.parse(payload, '2330.TW', start, end, get)
    assert result['coverage']['5']['observed'] == 2
    assert 0 < result['coverage']['5']['ratio'] < .01
    payload['data'].append(bar('2025-01-06', '2317'))
    with pytest.raises(ValueError, match='company mismatch'):
        history.parse(payload, '2330.TW', start, end, get)


def test_worker_reuses_same_close_and_preserves_history_on_provider_failure(monkeypatch, stored_calendar):
    monkeypatch.setenv('FINMIND_TOKEN', 'fixture')
    now = datetime(2025, 1, 6, 19, tzinfo=TAIPEI)
    monkeypatch.setattr(history, 'local_now', lambda: now)
    window = {'start':'2020-01-06', 'end':'2025-01-06'}
    put(history.STAGING + '2330.TW:' + history.DATASET, {
        'coverage_windows':[window], 'records':[{'date':'2025-01-06','open':100,'close':102}]})
    for feed in list(history.FEEDS)[:-1]:
        put(history.STAGING + '2330.TW:' + feed, {'coverage_windows':[window], 'records':[],
                                                    'catalog_contract':history.CATALOG_CONTRACT})
    fetch = Mock(side_effect=[{'status':200,'data':[]}, {'status':429}])
    monkeypatch.setattr(history, 'fetch_json', fetch)
    assert history.run(['2330.TW'])['symbols']['2330.TW']['state'] == 'updated'
    assert history.run(['2330.TW'])['symbols']['2330.TW']['state'] == 'cached'
    assert fetch.call_count == 1
    original = get(history.PREFIX + '2330.TW')
    assert original['raw_rows'][0]['close'] == 102
    assert original['source'] == history.SOURCE
    now = now.replace(day=7)
    assert history.run(['2330.TW'])['symbols']['2330.TW']['error_code'] == 'http_429'
    assert get(history.PREFIX + '2330.TW') == original
    assert get('annual:source:finmind')['next_attempt'] > 0


def test_free_windows_resume_without_publishing_incomplete_history(monkeypatch, stored_calendar):
    monkeypatch.setenv('FINMIND_TOKEN', 'fixture')
    monkeypatch.setattr(history, 'local_now', lambda: datetime(2025, 1, 6, 19, tzinfo=TAIPEI))
    fetch = Mock(return_value={'status':200,'data':[bar('2020-01-06')]})
    monkeypatch.setattr(history, 'fetch_json', fetch)
    result = history.run(['2330.TW'])
    assert result['symbols']['2330.TW']['state'] == 'backfilling'
    assert get(history.PREFIX + '2330.TW') is None
    first = fetch.call_args.args[1]
    assert first['dataset'] == 'TaiwanStockPrice'
    fetch.return_value = {'status':200,'data':[]}
    history.run(['2330.TW'])
    second = fetch.call_args.args[1]
    assert date.fromisoformat(second['start_date']) > date.fromisoformat(first['end_date'])


def test_assemble_adjusts_open_and_close_and_rejects_missing_event_coverage(stored_calendar):
    start, end = date(2020, 1, 6), date(2025, 1, 6)
    window = {'start':str(start),'end':str(end)}
    feed = next(iter(history.FEEDS))
    states = {name:{'coverage_windows':[window],'records':[]} for name in history.FEEDS}
    states[history.DATASET] = {'coverage_windows':[window], 'records':[
        {'date':'2025-01-03','open':98,'close':100},
        {'date':'2025-01-06','open':49,'close':51}]}
    states[feed]['records'] = [{'date':'2025-01-06','before':100,'after':50,'feed':feed}]
    result = history.assemble('2330.TW', start, end, states, get)
    assert result['rows'][0] == {'date':'2025-01-03','open':49,'close':50}
    assert result['raw_rows'][0]['close'] == 100
    assert result['coverage']['5']['observed'] == 2
    states[feed]['coverage_windows'] = []
    assert history.assemble('2330.TW', start, end, states, get) is None


def test_missing_historical_calendar_is_filled_before_provider_call(monkeypatch):
    monkeypatch.setenv('FINMIND_TOKEN', 'fixture')
    monkeypatch.setattr(history, 'local_now', lambda: datetime(2025, 1, 6, 19, tzinfo=TAIPEI))
    calendar = Mock()
    fetch = Mock()
    monkeypatch.setattr(history, 'calendar', calendar)
    monkeypatch.setattr(history, 'fetch_json', fetch)
    assert history.run(['2330.TW']) == {'state': 'calendar_updated', 'year': 2025}
    calendar.assert_called_once_with(2025)
    fetch.assert_not_called()


def test_catalog_request_does_not_send_unsupported_company_parameters():
    assert history.request_parameters('TaiwanStockSplitPrice','2330.TW','2020-01-06','2025-01-06') == {
        'dataset':'TaiwanStockSplitPrice'}
    assert history.request_parameters('TaiwanStockParValueChange','2330.TW','2020-01-06','2025-01-06') == {
        'dataset':'TaiwanStockParValueChange','start_date':'2020-01-06'}
    assert history.request_parameters('TaiwanStockPrice','2330.TW','2020-01-06','2025-01-06')['data_id'] == '2330'


def test_catalog_cache_is_shared_without_another_provider_request(monkeypatch, stored_calendar):
    monkeypatch.setenv('FINMIND_TOKEN', 'fixture')
    monkeypatch.setattr(history, 'local_now', lambda: datetime(2025,1,6,19,tzinfo=TAIPEI))
    window = {'start':'2020-01-06','end':'2025-01-06'}
    feed = 'TaiwanStockSplitPrice'
    for symbol in ('2330.TW','2317.TW'):
        for name in (history.DATASET, *history.FEEDS):
            if name == feed:
                continue
            put(history.STAGING + symbol + ':' + name, {
                'coverage_windows':[window], 'records':([{'date':'2025-01-06','open':100,'close':102}]
                                                         if name == history.DATASET else []),
                'catalog_contract':history.CATALOG_CONTRACT})
    fetch = Mock(return_value={'status':200,'data':[{'stock_id':'9999','date':'2025-01-06'}]})
    monkeypatch.setattr(history,'fetch_json',fetch)
    result = history.run(['2330.TW','2317.TW'])
    assert fetch.call_count == 1
    assert all(row['state']=='updated' for row in result['symbols'].values())
