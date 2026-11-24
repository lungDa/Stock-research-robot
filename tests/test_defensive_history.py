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
    fetch = Mock(side_effect=[{'status': 200, 'data': [bar('2025-01-06')]}, {'status': 429}])
    monkeypatch.setattr(history, 'fetch_json', fetch)
    assert history.run(['2330.TW'])['symbols']['2330.TW']['state'] == 'updated'
    assert history.run(['2330.TW'])['symbols']['2330.TW']['state'] == 'cached'
    assert fetch.call_count == 1
    original = get(history.PREFIX + '2330.TW')
    now = now.replace(day=7)
    assert history.run(['2330.TW'])['symbols']['2330.TW']['error_code'] == 'http_429'
    assert get(history.PREFIX + '2330.TW') == original
    assert get('annual:source:finmind')['next_attempt'] > 0


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
