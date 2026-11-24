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
    put('defensive:adjusted:2330.TW', {'as_of': '2026-11-24', 'rows': [{'date': '2026-11-24', 'close': 100}],
                                     'coverage': {'1': {'observed': 5, 'sessions': 10}}})
    put(audit.SNAPSHOT, {'state': 'evaluated', 'as_of': '2026-11-24',
                         'periods': {'1': {'tw_electronics': {'eligible': 1}}}, 'coverage': {'current_history': 1}})
    result = audit.run(now, samples=2)
    assert result['latency']['precomputed_ranking_read']['usable_samples'] == 2
    assert result['coverage']['current_history_ratio'] == .5
    assert result['coverage']['historical_counts_for_current_stocks']['1']['observed_ratio'] == .5
    assert result['coverage']['published_applicable_data_99_percent'] == 'unverified'


def test_audit_distinguishes_stored_index_prices_from_usable_returns():
    now = datetime(2026, 11, 24, 19, tzinfo=TAIPEI)
    put('recommendations:calendar:2026', {'year': 2026, 'closed': [], 'opened': []})
    put('defensive:index:sox', {'rows': [{'date': '2026-11-23', 'close': 100}]})
    put('defensive:tw_indices', {'rows': {
        '2026-11-23': {'closes': {'tw_electronics': 100}},
        '2026-11-24': {'closes': {'tw_electronics': 98}},
    }})
    put(audit.RISK_SNAPSHOT, {'verified': True, 'session_date': '2026-11-23'})
    result = audit.run(now, samples=1)
    ready = result['benchmark_readiness']
    assert ready['target_session'] == '2026-11-24'
    assert ready['benchmarks']['sox']['state'] == 'publication_times_missing'
    assert ready['benchmarks']['sox']['stored_closes'] == 1
    assert ready['benchmarks']['sox']['stored_time_records'] == 0
    assert ready['benchmarks']['tw_electronics']['state'] == 'return_ready'
    assert result['risk_snapshot'] == {'as_of': '2026-11-23', 'matches_target': False}
