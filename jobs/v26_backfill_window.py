"""V2.6 adaptive backfill window; fail open when coverage is unverified.

A validated completeness snapshot must explicitly include all TW/TWO ordinary
stocks. Never infer 95% coverage from the presence of cached records.
"""
import sys
from app.db import get
from app.services.freshness import local_now


def should_run(now=None, snapshot=None):
    now = now or local_now()
    if not 8 <= now.hour < 24:
        if snapshot is None:
            snapshot = get('v26:coverage:verified', {})
        verified = (
            isinstance(snapshot, dict)
            and snapshot.get('scope') == 'TW_TWO_ORDINARY_STOCKS'
            and snapshot.get('verified') is True
            and snapshot.get('partial') is False
            and isinstance(snapshot.get('ratio'), (int, float))
            and not isinstance(snapshot.get('ratio'), bool)
            and 0.95 <= snapshot['ratio'] <= 1
            and isinstance(snapshot.get('at'), (int, float))
            and 0 <= now.timestamp() - snapshot['at'] <= 86400
        )
        if verified:
            return False
    return True


if __name__ == '__main__':
    if not should_run():
        print('SKIP: verified >=95% full-market completeness; daytime-only schedule')
        sys.exit(10)
    print('RUN: backfill window open (or completeness not verified)')
