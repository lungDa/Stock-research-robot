from datetime import date, datetime
from unittest.mock import Mock

import pytest

from app.db import get, put
from app.providers import twse_indices
from app.services.freshness import TAIPEI
from jobs import refresh_defensive_tw_indices as worker


def test_twse_parser_uses_domestic_price_index_only():
    day = date(2026, 10, 28)
    table = {'title': '115年10月28日 價格指數(臺灣證券交易所)',
             'fields': ['指數', '收盤指數'],
             'data': [['電子工業類指數', '2,938.42'], ['半導體類指數', '1,564.79']]}
    payload = {'stat': 'OK', 'type': 'IND', 'date': '20261028',
               'tables': [{**table, 'title': '報酬指數(臺灣證券交易所)'}, table]}
    assert twse_indices.parse(payload, day) == {'tw_electronics': 2938.42, 'tw_semiconductors': 1564.79}
    with pytest.raises(ValueError, match='date'):
        twse_indices.parse(payload, day.replace(day=29))
    table['data'].append(['半導體類指數', '1'])
    with pytest.raises(ValueError, match='duplicated'):
        twse_indices.parse(payload, day)


def test_backfill_resumes_and_cools_down_failed_session(monkeypatch):
    for year in range(2020, 2026):
        put(f'recommendations:calendar:{year}', {'year': year, 'closed': [], 'opened': []})
    now = datetime(2025, 1, 10, 19, tzinfo=TAIPEI)
    values = {'tw_electronics': 2000., 'tw_semiconductors': 1000.}

    def fetch(day):
        if day == now.date():
            raise TimeoutError('unavailable')
        return values

    download = Mock(side_effect=fetch)
    monkeypatch.setattr(twse_indices, 'fetch', download)
    monkeypatch.setattr(worker, 'local_now', lambda: now)
    first = worker.run(now)
    assert first['observed'] == 1 and first['errors'][0]['date'] == '2025-01-10'
    assert worker.run(now)['observed'] == 3
    assert [str(call.args[0]) for call in download.call_args_list] == [
        '2025-01-10', '2025-01-09', '2025-01-08', '2025-01-07',
    ]
    assert get(worker.HISTORY)['rows']['2025-01-09']['closes'] == values
