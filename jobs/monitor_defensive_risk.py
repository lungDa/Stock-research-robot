"""Evaluate verified close-based risk once per Taiwan session."""
from datetime import datetime, time
import json

from app.db import get, init_db, leased, put_many
from app.services.defensive_model import BENCHMARK_WEIGHTS, RiskRule, risk_level
from app.services.defensive_notifications import RISK_SNAPSHOT
from app.services.defensive_research import market_context
from app.services.freshness import TAIPEI, local_now

DEFAULT_RULES = [
    RiskRule(.015, .010, 2, .008),
    RiskRule(.025, .015, 2, .015),
    RiskRule(.035, .022, 3, .022),
    RiskRule(.050, .030, 3, .032),
]


def run(now=None):
    now = now or local_now()
    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    now = now.astimezone(TAIPEI)
    if now.time() < time(18, 17):
        return {'state': 'waiting_for_close'}
    init_db()
    with leased(RISK_SNAPSHOT + ':worker', 120) as acquired:
        if not acquired:
            return {'state': 'busy'}
        docs, end, closes, benchmarks = market_context(now, history_days=45)
        if end is None:
            return {'state': 'calendar_missing'}
        if end != now.date():
            return {'state': 'market_closed'}
        existing = get(RISK_SNAPSHOT, {})
        if existing.get('session_date') == str(end) and existing.get('verified') is True:
            archive_key = f'{RISK_SNAPSHOT}:session:{end}'
            if get(archive_key) is None:
                put_many({archive_key: existing})
            return {'state': 'cached', 'level': existing['level']}
        settings = get('defensive:risk:configuration', {})
        rules = [RiskRule(**item) for item in settings['rules']] if 'rules' in settings else DEFAULT_RULES
        weights = settings.get('weights', BENCHMARK_WEIGHTS)
        returns = {}
        missing = {}
        for key, (series, detail) in benchmarks.items():
            if series is None:
                missing[key] = detail['state']
            else:
                value = series.loc[closes[-1]]
                if value != value:
                    missing[key] = 'session_return_missing'
                else:
                    returns[key] = float(value)
        if missing:
            return {'state': 'insufficient_data', 'session_date': str(end), 'missing': missing}
        sector = docs.get('defensive:tw_indices', {}).get('rows', {}).get(str(end), {})
        try:
            observed = datetime.fromisoformat(sector.get('observed_at'))
            if observed.tzinfo is None:
                return {'state': 'close_timestamp_unverified'}
            observed = observed.astimezone(TAIPEI)
            if observed.date() != end or observed > now or observed.time() < time(13, 30):
                return {'state': 'close_timestamp_unverified'}
        except (TypeError, ValueError):
            return {'state': 'close_timestamp_unverified'}
        level = risk_level(returns, rules, weights)
        if level is None:
            return {'state': 'insufficient_data', 'session_date': str(end)}
        snapshot = {
            'verified': True, 'level': level, 'session_date': str(end),
            'observed_at': max(observed, datetime.combine(end, time(18, 17), TAIPEI)).isoformat(),
            'ranking_as_of': str(end), 'returns': returns, 'basis': 'verified_daily_close',
        }
        put_many({RISK_SNAPSHOT: snapshot, f'{RISK_SNAPSHOT}:session:{end}': snapshot})
        return {'state': 'updated', 'session_date': str(end), 'level': level}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False))
