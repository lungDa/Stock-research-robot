from datetime import datetime, timedelta

import pandas as pd

from app.db import get
from app.services.defensive_model import BENCHMARK_WEIGHTS
from app.services.defensive_notifications import RISK_SNAPSHOT
from app.services.freshness import TAIPEI
from jobs import monitor_defensive_risk as job


def test_monitor_requires_five_verified_benchmarks_and_does_not_reissue(monkeypatch):
    now = datetime(2026, 11, 24, 18, 25, tzinfo=TAIPEI)
    day = now.date()
    closes = pd.DatetimeIndex([now.replace(hour=13, minute=30)])
    docs = {'defensive:tw_indices': {'rows': {str(day): {'observed_at': now.isoformat()}}}}
    inputs = {name: (pd.Series([-.029], index=closes), {'state': 'evaluated'})
              for name in BENCHMARK_WEIGHTS}
    inputs['sox'] = (None, {'state': 'publication_times_missing'})
    monkeypatch.setattr(job, 'market_context', lambda *args, **kwargs: (docs, day, closes, inputs))
    assert job.run(now)['missing'] == {'sox': 'publication_times_missing'}
    assert get(RISK_SNAPSHOT) is None
    inputs['sox'] = (pd.Series([-.029], index=closes), {'state': 'evaluated'})
    result = job.run(now)
    assert result['state'] == 'updated' and result['level'] == 3
    saved = get(RISK_SNAPSHOT)
    assert saved['observed_at'] == now.isoformat()
    assert job.run(now + timedelta(hours=1)) == {'state': 'cached', 'level': 3}
    assert get(RISK_SNAPSHOT) == saved
