from datetime import datetime
import json

from app.db import put
from app.services.defensive_research import report
from app.services.freshness import TAIPEI


def test_report_uses_cached_prices_marks_gaps_and_prevents_self_comparison():
    now = datetime(2026, 11, 20, 19, tzinfo=TAIPEI)
    for year in range(2021, 2027):
        put(f'recommendations:calendar:{year}', {'year': year, 'closed': [], 'opened': []})
    days = ['2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20', '2026-11-23']
    rows = [{'date': day, 'close': close} for day, close in zip(days, [100, 102, 101, 103, 900])]
    put('defensive:adjusted:2330.TW', {'as_of': days[-1], 'rows': rows})
    put('defensive:tw_indices', {'rows': {
        day: {'closes': {'tw_electronics': close}}
        for day, close in zip(days, [100, 98, 99, 97, 7])
    }})
    put('defensive:index:nasdaq_100', {'rows': rows})
    result = report('2330.TW', now, min_pairs=2)
    assert result['as_of'] == '2026-11-20'
    assert result['benchmarks']['2330.TW']['state'] == 'self_benchmark'
    assert result['benchmarks']['nasdaq_100']['state'] == 'publication_times_missing'
    assert result['benchmarks']['sox']['state'] == 'benchmark_history_missing'
    electronics = result['benchmarks']['tw_electronics']
    assert electronics['basis'] == 'same_session_close_descriptive'
    assert electronics['periods']['1']['pairs'] == 3
    assert electronics['periods']['1']['up_probability'] == 1
    assert electronics['periods']['5']['paired_coverage'] < .01
    json.dumps(result, allow_nan=False)
    put('defensive:index:sox', {
        'rows': [{'date': day, 'close': close} for day, close in
                 zip(days[:3], [100, 98, 96])],
        'session_closes': [day + 'T16:00:00-05:00' for day in days[:3]],
        'published_at': {day: day + 'T17:00:00-05:00' for day in days[:3]},
    })
    sox = report('2330.TW', now, min_pairs=2)['benchmarks']['sox']
    assert sox['basis'] == 'us_publication_to_next_tw_open'
    assert sox['periods']['1']['pairs'] == 2
    assert sox['periods']['1']['up_probability'] == .5


def test_report_returns_missing_calendar_without_guessing():
    now = datetime(2026, 11, 20, 19, tzinfo=TAIPEI)
    assert report('2317.TW', now)['state'] == 'calendar_missing'
