from jobs import refresh_defensive_inputs as job


def test_input_refresh_attempts_all_sources_and_keeps_errors_separate(monkeypatch):
    calls = []

    def failed_fred():
        calls.append('fred')
        raise RuntimeError('upstream secret')

    def twse():
        calls.append('twse')
        return {'state': 'partial', 'observed': 2}

    def adjusted(symbols):
        calls.append(symbols)
        return {'state': 'not_configured'}

    monkeypatch.setattr(job.refresh_defensive_indices, 'run', failed_fred)
    monkeypatch.setattr(job.refresh_defensive_tw_indices, 'run', twse)
    monkeypatch.setattr(job.refresh_defensive_history, 'run', adjusted)
    from app.db import get

    report = job.run()
    assert get('defensive:input_refresh:status') == report
    result = report['sources']
    assert calls == ['fred', 'twse', ['2330.TW']]
    assert result == {
        'us_indices': {'state': 'failed', 'error_type': 'RuntimeError'},
        'tw_indices': {'state': 'partial', 'observed': 2},
        'tsmc_adjusted': {'state': 'not_configured'},
    }


def test_universe_backfill_preserves_first_unprocessed_symbol_on_budget_stop(monkeypatch):
    from datetime import datetime
    from app.db import get, put
    from app.services.freshness import TAIPEI
    from jobs import refresh_defensive_universe as universe

    now = datetime(2026, 11, 24, 19, tzinfo=TAIPEI)
    put('v26:universe:verified_symbols', {'at': now.timestamp(), 'verified': True,
        'symbols': ['2330.TW', '2303.TW', '2317.TW', '6488.TWO']})
    batches = []

    def refresh(batch):
        batches.append(batch)
        if len(batches) == 1:
            return {'state': 'partial', 'symbols': {
                '2303.TW': {'state': 'updated'}, '2317.TW': {'state': 'budget'}}}
        return {'state': 'finished', 'symbols': {symbol: {'state': 'cached'} for symbol in batch}}

    monkeypatch.setattr(universe.refresh_defensive_history, 'run', refresh)
    assert universe.run(now)['advanced'] == 1
    assert get(universe.CURSOR)['last_symbol'] == '2303.TW'
    assert universe.run(now)['advanced'] == 2
    assert universe.run(now)['advanced'] == 2
    assert batches == [['2303.TW', '2317.TW'], ['2317.TW', '6488.TWO'], ['2303.TW', '2317.TW']]
