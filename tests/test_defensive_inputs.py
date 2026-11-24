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
    result = job.run()['sources']
    assert calls == ['fred', 'twse', ['2330.TW']]
    assert result == {
        'us_indices': {'state': 'failed', 'error_type': 'RuntimeError'},
        'tw_indices': {'state': 'partial', 'observed': 2},
        'tsmc_adjusted': {'state': 'not_configured'},
    }
