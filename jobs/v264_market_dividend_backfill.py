"""V2.6.4 bounded whole-market paid-dividend backfill.

Only the independently verified TWSE/TPEx ordinary-stock snapshot is eligible.
The existing MOPS worker owns source budgets, retries, and per-year checkpoints.
"""
import json
import time
from app.db import get, init_db, put
from jobs.refresh_cash_dividends import run as refresh

SNAPSHOT_TTL = 8 * 86400
BATCH_SIZE = 20
CURSOR_KEY = 'v264:cash_dividends:cursor'
PROGRESS_KEY = 'v264:cash_dividends:progress'


def verified_symbols(snapshot, audit, now=None):
    now = time.time() if now is None else now
    if not isinstance(snapshot, dict) or not isinstance(audit, dict):
        return []
    stamp = snapshot.get('at')
    if (type(stamp) not in (int, float) or not 0 <= now - stamp <= SNAPSHOT_TTL
            or snapshot.get('verified') is not True
            or audit.get('verified') is not True
            or audit.get('scope') != 'TW_TWO_ORDINARY_STOCKS'
            or audit.get('at') != stamp):
        return []
    import re
    symbols = snapshot.get('symbols')
    if not isinstance(symbols, list) or not symbols:
        return []
    if len(set(symbols)) != len(symbols) or len(symbols) != audit.get('stock_count'):
        return []
    if not all(isinstance(s, str) and re.fullmatch(r'\d{4}\.(TW|TWO)', s) for s in symbols):
        return []
    return sorted(symbols)


def run():
    init_db()
    now = time.time()
    snapshot = get('v26:universe:verified_symbols', {})
    audit = get('v26:universe:audit', {})
    symbols = verified_symbols(snapshot, audit, now)
    if not symbols:
        result = {'state': 'blocked_unverified_universe', 'at': now,
                  'reason': '官方上市上櫃普通股母體尚未完成有效期內的完整核對',
                  'requests': 0, 'processed': 0}
        put(PROGRESS_KEY, result)
        return result

    from app.db import leased
    with leased('v264:market:cursor', seconds=160) as owned:
        if not owned:
            return {'state': 'busy', 'requests': 0, 'processed': 0}
        saved = get(CURSOR_KEY, {})
        # A new universe snapshot must restart scanning at the beginning.
        offset = int(saved.get('offset', 0)) if saved.get('snapshot_at') == snapshot['at'] else 0
        offset %= len(symbols)
        batch = symbols[offset:offset + BATCH_SIZE]
        if not batch:
            offset = 0
            batch = symbols[:BATCH_SIZE]
        outcome = refresh(symbols=batch, years=5, max_requests=4)
        state = outcome.get('state')
        # Do not skip a batch that could not run because of cooldown or lease.
        advanced = state not in ('busy', 'cooldown', 'failed', 'limited')
        next_offset = (offset + len(batch)) % len(symbols) if advanced else offset
        if advanced:
            put(CURSOR_KEY, {'offset': next_offset, 'snapshot_at': snapshot['at'],
                             'updated_at': time.time()})
        result = {'state': state, 'at': time.time(), 'snapshot_at': snapshot['at'],
                  'universe_count': len(symbols), 'batch_count': len(batch),
                  'cursor_before': offset, 'cursor_after': next_offset,
                  'cycle_completed': bool(advanced and next_offset == 0),
                  'requests': outcome.get('cash_requests', 0),
                  'updated_fields': outcome.get('updated_fields', 0),
                  'failed_feeds': outcome.get('failed_feeds', 0),
                  'advanced': advanced,
                  'note': '游標輪詢不代表五年資料已補齊；逐年度仍以來源證明稽核為準'}
        put(PROGRESS_KEY, result)
        return result


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False))
