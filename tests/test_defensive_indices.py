from datetime import date, datetime, timezone
from unittest.mock import Mock

import pandas as pd
import pytest

from app.db import get
from app.providers import fred_indices
from app.services.defensive_model import align_us_index_history
from jobs import refresh_defensive_indices as job


def test_fred_series_identity_and_holiday_rows():
    start, end = date(2025, 7, 3), date(2025, 7, 7)
    body = 'observation_date,NASDAQSOX\n2025-07-03,100\n2025-07-04,.\n2025-07-07,110\n'
    rows = fred_indices.parse_csv(body, 'NASDAQSOX', start, end)
    assert [row['date'] for row in rows] == ['2025-07-03', '2025-07-07']
    with pytest.raises(ValueError, match='header'):
        fred_indices.parse_csv(body, 'NASDAQ100', start, end)
    with pytest.raises(ValueError, match='unique'):
        fred_indices.parse_csv(body + '2025-07-07,111\n', 'NASDAQSOX', start, end)


def test_us_half_day_and_late_publication_use_the_next_taiwan_open():
    closes = pd.DatetimeIndex(['2025-07-02 16:00', '2025-07-03 13:00', '2025-07-07 16:00'],
                             tz='America/New_York')
    opens = pd.DatetimeIndex(['2025-07-03 09:00', '2025-07-04 09:00', '2025-07-07 09:00',
                              '2025-07-08 09:00'], tz='Asia/Taipei')
    history = {'rows': [{'date': day, 'close': price} for day, price in
                       [('2025-07-02', 100), ('2025-07-03', 110), ('2025-07-07', 120)]]}
    publication = {'2025-07-02': closes[0], '2025-07-03': '2025-07-04T09:01:00+08:00'}
    result = align_us_index_history(history, closes, opens, publication)
    assert result.iloc[2] == pytest.approx(.10)
    assert result.dropna().index.tolist() == [opens[2]]
    assert align_us_index_history(history, closes, opens, {}).isna().all()
    publication['2025-07-03'] = '2025-07-03T12:00:00-04:00'
    with pytest.raises(ValueError, match='precedes'):
        align_us_index_history(history, closes, opens, publication)


def test_worker_preserves_an_index_if_new_download_regresses(monkeypatch):
    recent = [{'date': '2025-07-07', 'close': 100}]
    old = [{'date': '2025-07-03', 'close': 90}]
    fetch = Mock(side_effect=[recent, recent, old, recent])
    monkeypatch.setattr(fred_indices, 'fetch', fetch)
    now = datetime(2025, 7, 8, 12, tzinfo=timezone.utc)
    assert job.run(now)['state'] == 'finished'
    assert job.run(now)['indices']['sox']['state'] == 'cached'
    assert job.run(now.replace(hour=14))['state'] == 'partial'
    assert get(job.PREFIX + 'nasdaq_100')['rows'] == recent
