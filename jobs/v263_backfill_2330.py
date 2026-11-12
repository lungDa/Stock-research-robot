"""Bounded 2330 historical paid-dividend verification and backfill.

Uses the existing official MOPS worker, shared Neon documents, lease and
provider cooldown. Never treats a worker attempt as verified data.
"""
import json
from app.db import init_db, put
from jobs.v263_paid_dividend_audit import read
from jobs.refresh_cash_dividends import run as backfill

SYMBOL = '2330.TW'
YEARS = (2021, 2022, 2023)


def run():
    init_db()
    before = read(SYMBOL, YEARS)
    pending = before['missing_years']
    if not pending:
        outcome = {'state': 'already_present', 'cash_requests': 0}
    else:
        # Existing worker rotates over requested years. Request 6 years to
        # include 2021 as of 2026; never bypass its request/cooldown limits.
        from app.services.freshness import local_now
        window = max(1, local_now().year - min(pending))
        outcome = backfill(symbols=[SYMBOL], years=window, max_requests=4)
    after = read(SYMBOL, YEARS)
    report = {'symbol': SYMBOL, 'years': list(YEARS), 'before': before,
              'worker': outcome, 'after': after,
              'verified_complete': not after['missing_years']}
    put('v263:paid_dividend:2330:audit', report)
    return report


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False))
