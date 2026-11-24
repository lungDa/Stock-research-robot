"""Consume a verified risk snapshot and send opted-in LINE notices."""
import argparse
from datetime import datetime
import hashlib
import json

from app.channels.line import quota
from app.db import get, init_db, leased, put
from app.services.accounts import member_users
from app.services.defensive_notifications import RISK_SNAPSHOT, event, message, preference
from app.services.freshness import local_now
from jobs.rank_defensive_market import SNAPSHOT
from jobs.recommend import deliver


def run(*, send=False, now=None):
    now = now or local_now()
    init_db()
    with leased('defensive:line:worker', 900) as acquired:
        if not acquired:
            return {'state': 'busy'}
        risk = get(RISK_SNAPSHOT, {})
        level = risk.get('level')
        stamp = risk.get('observed_at')
        if risk.get('verified') is not True or type(level) is not int or not 0 <= level <= 4:
            return {'state': 'risk_unavailable'}
        try:
            age = (now - datetime.fromisoformat(stamp)).total_seconds()
        except (TypeError, ValueError):
            return {'state': 'risk_unavailable'}
        if not 0 <= age <= 5400:
            return {'state': 'risk_stale'}

        ranking = get(SNAPSHOT, {})
        items = []
        if level >= 3 and risk.get('ranking_as_of') == ranking.get('as_of') and ranking.get('as_of'):
            items = ranking.get('screened_periods', {}).get('1', {}).get('combined', {}).get('items', [])[:10]
        symbols = [item['symbol'] for item in items]
        ranking_stamp = ranking.get('generated_at') if items else None
        observed = datetime.fromisoformat(stamp)
        emitted = failed = 0
        remaining = None
        for user in member_users():
            if not preference(user).get('enabled'):
                continue
            state_key = 'defensive:line:state:' + user
            previous = get(state_key, {})
            previous_stamp = previous.get('observed_at')
            if previous_stamp:
                prior = datetime.fromisoformat(previous_stamp)
                if prior > observed:
                    continue
                if prior == observed and (not ranking_stamp or ranking_stamp == previous.get('ranking_stamp')):
                    continue
            kind = event(level, previous, symbols)
            state = {**previous, 'level': level, 'observed_at': stamp, 'ranking_stamp': ranking_stamp}
            if kind:
                body = message(kind, level, stamp, items)
                if send:
                    identity = stamp if kind != 'ranking_changed' else json.dumps([stamp, symbols])
                    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
                    key = f'defensive:line:outbox:{user}:{digest}'
                    try:
                        if remaining is None:
                            remaining = quota()
                        remaining = deliver(user, key, [body], False, remaining)
                    except (OSError, RuntimeError):
                        failed += 1
                        continue
                state.update(alerted_level=level, symbols=symbols)
                emitted += 1
            if send:
                put(state_key, state)
        return {'state': 'partial' if failed else 'finished', 'events': emitted, 'failed': failed,
                'preview': not send}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(send=args.send), ensure_ascii=False))
