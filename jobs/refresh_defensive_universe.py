"""Advance the adjusted-history backfill through the verified Taiwan universe."""
import json

from app.db import get, init_db, leased, put
from app.services.freshness import local_now
from jobs import refresh_defensive_history

CURSOR = 'defensive:universe_backfill_cursor'


def run(now=None):
    now = now or local_now()
    init_db()
    with leased(CURSOR + ':worker', 180) as acquired:
        if not acquired:
            return {'state': 'busy'}
        catalog = get('v26:universe:verified_symbols', {})
        if catalog.get('verified') is not True or not 0 <= now.timestamp() - catalog.get('at', 0) <= 48 * 3600:
            return {'state': 'universe_unverified'}
        # TSMC is refreshed separately as a risk benchmark.
        symbols = sorted(set(catalog.get('symbols', [])) - {'2330.TW'})
        if not symbols:
            return {'state': 'universe_empty'}
        last = get(CURSOR, {}).get('last_symbol', '')
        batch = [symbol for symbol in symbols if symbol > last][:2]
        if not batch:
            batch = symbols[:2]
        result = refresh_defensive_history.run(batch)
        statuses = result.get('symbols', {})
        advanced = []
        for symbol in batch:
            status = statuses.get(symbol, {}).get('state')
            if status not in ('cached', 'updated', 'cooldown', 'failed'):
                break
            advanced.append(symbol)
        if advanced:
            put(CURSOR, {'last_symbol': advanced[-1], 'checked_at': now.isoformat()})
        return {'state': result['state'], 'universe': len(symbols), 'batch': result,
                'advanced': len(advanced)}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, allow_nan=False))
