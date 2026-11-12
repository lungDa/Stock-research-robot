from datetime import datetime, timezone, timedelta
from jobs.v26_backfill_window import should_run

TZ = timezone(timedelta(hours=8))

def snapshot(now, ratio=0.96):
    return {'scope': 'TW_TWO_ORDINARY_STOCKS', 'verified': True,
            'partial': False, 'ratio': ratio, 'at': now.timestamp()}

def test_unverified_stays_full_day():
    now = datetime(2026, 11, 13, 2, 0, tzinfo=TZ)
    assert should_run(now, {}) is True
    assert should_run(now, {'ratio': 0.99}) is True

def test_verified_high_coverage_restricts_night():
    now = datetime(2026, 11, 13, 2, 0, tzinfo=TZ)
    assert should_run(now, snapshot(now)) is False
    assert should_run(now.replace(hour=8), snapshot(now)) is True

def test_partial_stale_and_low_coverage_do_not_stop():
    now = datetime(2026, 11, 13, 2, 0, tzinfo=TZ)
    partial = snapshot(now)
    partial['partial'] = True
    assert should_run(now, partial)
    assert should_run(now, snapshot(now, 0.949))
    stale = snapshot(now)
    stale['at'] -= 90000
    assert should_run(now, stale)
