from datetime import datetime

from app.db import put
from app.services.freshness import TAIPEI
from jobs import audit_defensive_readiness as audit


def test_audit_reports_coverage_separately_from_query_latency():
    now = datetime(2026, 11, 24, 19, tzinfo=TAIPEI)
    empty = audit.run(now, samples=2)
    assert empty['latency']['precomputed_ranking_read']['state'] == 'insufficient_data'
    assert empty['coverage']['current_adjusted_stocks'] is None
    put('recommendations:calendar:2026', {'year': 2026, 'closed': [], 'opened': []})
    put(audit.CATALOG, {'verified': True, 'symbols': ['2330.TW', '2317.TW'], 'at': now.timestamp()})
    put('defensive:adjusted:2330.TW', {'as_of': '2026-11-24', 'rows': [{'date': '2026-11-24'}],
                                     'coverage': {'1': {'observed': 5, 'sessions': 10}}})
    put(audit.SNAPSHOT, {'state': 'evaluated', 'as_of': '2026-11-24',
                         'periods': {'1': {'tw_electronics': {'eligible': 1}}}, 'coverage': {'current_history': 1}})
    result = audit.run(now, samples=2)
    assert result['latency']['precomputed_ranking_read']['usable_samples'] == 2
    assert result['coverage']['current_history_ratio'] == .5
    assert result['coverage']['historical_counts_for_current_stocks']['1']['observed_ratio'] == .5
    assert result['coverage']['published_applicable_data_99_percent'] == 'unverified'
