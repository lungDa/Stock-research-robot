"""Refresh one year of market-wide TPEx EPS, using the existing annual EPS cache."""
import time
from datetime import datetime, timezone

from app.db import get, get_many, init_db, leased, put, put_many
from app.providers.source_errors import describe
from app.providers.tpex_eps import PROVENANCE, fetch_year
from app.services.data_queue import source_slot
from app.services.freshness import local_now


def run():
    init_db()
    with leased('annual:worker', 180) as owned:
        if not owned:
            return {'state': 'busy'}
        today = local_now().date()
        now = time.time()
        for year in range(today.year - 1, today.year - 6, -1):
            key = f'eps:tpex:state:{year}'
            if now < get(key, {}).get('next_attempt', 0):
                continue
            if not source_slot('tpex_eps', 6):
                return {'state': 'limited'}
            try:
                report = fetch_year(year, today)
            except Exception as exc:
                detail = describe(exc, '櫃買中心年度 EPS')
                delay = 3600 if detail['error_code'] in ('timeout', 'connection') else 86400
                put(key, {'next_attempt': now + delay, **detail})
                return {'state': 'failed', 'year': year, **detail}

            records = {f'eps:official:{code}.TWO': row for code, row in report.items()}
            keys = list(records)
            documents = {}
            updated_at = datetime.now(timezone.utc).isoformat()
            for start in range(0, len(keys), 80):
                batch = keys[start:start + 80]
                existing = get_many(batch)
                for stock_key in batch:
                    document = existing.get(stock_key, {})
                    rows = document.get('rows', {})
                    previous = rows.get(str(year), {})
                    previous_source = previous.get('field_sources', {}).get('eps', {})
                    if previous.get('eps') is not None and previous_source.get('provenance') != PROVENANCE:
                        continue
                    row = records[stock_key]
                    fields = {**previous.get('field_sources', {}), **row['field_sources']}
                    rows[str(year)] = {**previous, **row, 'field_sources': fields}
                    documents[stock_key] = {**document, 'rows': rows, 'updated_at': updated_at}
            documents[key] = {
                'status': 'ok', 'next_attempt': now + 30 * 86400, 'rows': len(report),
            }
            put_many(documents)
            return {'state': 'updated', 'year': year, 'rows': len(report), 'updated': len(documents) - 1}
        return {'state': 'cached'}


if __name__ == '__main__':
    print(run())
