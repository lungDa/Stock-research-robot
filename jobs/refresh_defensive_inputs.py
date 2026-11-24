"""Refresh the independent sources feeding the defensive close monitor."""
import json

from app.services.freshness import local_now
from jobs import refresh_defensive_history, refresh_defensive_indices, refresh_defensive_tw_indices


def run():
    steps = (
        ('us_indices', refresh_defensive_indices.run),
        ('tw_indices', refresh_defensive_tw_indices.run),
        ('tsmc_adjusted', lambda: refresh_defensive_history.run(['2330.TW'])),
    )
    started = local_now()
    results = {}
    for name, refresh in steps:
        try:
            results[name] = refresh()
        except Exception as exc:
            # An independent provider should still have a chance to publish.
            # Connection errors may include credentials, so log only the type.
            results[name] = {'state': 'failed', 'error_type': type(exc).__name__}
    return {'started_at': started.isoformat(), 'sources': results}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, allow_nan=False))
