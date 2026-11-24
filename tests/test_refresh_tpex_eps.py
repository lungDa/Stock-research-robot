from datetime import datetime, timezone

import requests

from app.db import get, put
from app.services.multifactor import annual_rows
from jobs import refresh_tpex_eps as worker


def test_report_populates_missing_eps_and_preserves_existing_sources(monkeypatch):
    monkeypatch.setattr(worker, 'local_now', lambda: datetime(2026, 11, 24, tzinfo=timezone.utc))
    monkeypatch.setattr(worker, 'source_slot', lambda *_: True)
    row = {
        'eps': 15.29,
        'as_of': '2026-11-24',
        'field_sources': {'eps': {'provenance': worker.PROVENANCE, 'as_of': '2026-11-24'}},
    }
    monkeypatch.setattr(worker, 'fetch_year', lambda *_: {'6488': row, '1111': row})
    put('eps:official:1111.TWO', {'rows': {'2025': {'eps': 2.0}}})
    put('eps:official:6488.TWO', {'rows': {'2024': {'eps': 21.06}}})

    assert worker.run()['updated'] == 1
    assert get('eps:official:1111.TWO')['rows']['2025']['eps'] == 2.0
    assert get('eps:official:6488.TWO')['rows']['2024']['eps'] == 21.06
    assert annual_rows('Ualice', '6488.TWO')['2025']['eps'] == 15.29

    put('financial:official:6488.TWO', {'rows': {'2025': {
        'eps': 15.30, 'field_sources': {'eps': {'as_of': '2026-04-01'}},
    }}})
    assert annual_rows('Ualice', '6488.TWO')['2025']['eps'] == 15.30


def test_timeout_cools_down_failed_year_and_allows_next_year(monkeypatch):
    monkeypatch.setattr(worker, 'local_now', lambda: datetime(2026, 11, 24, tzinfo=timezone.utc))
    monkeypatch.setattr(worker.time, 'time', lambda: 1000)
    monkeypatch.setattr(worker, 'source_slot', lambda *_: True)

    def fetch(year, _today):
        if year == 2025:
            raise requests.ReadTimeout('internal details')
        return {'6488': {'eps': 21.06, 'field_sources': {'eps': {}}}}

    monkeypatch.setattr(worker, 'fetch_year', fetch)
    assert worker.run()['error_code'] == 'timeout'
    assert get('eps:tpex:state:2025')['next_attempt'] == 4600
    assert get('eps:official:6488.TWO') is None
    assert worker.run()['year'] == 2024
