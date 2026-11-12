from jobs import v26_universe_audit as module


def test_official_registry_drives_verified_universe(monkeypatch):
    now = 1000000.0
    docs = {
        'official:catalog:TW': {'at': now, 'source': module.ENDPOINTS['TW'],
                                'scope': 'OFFICIAL_COMPANY_REGISTRY',
                                'data': {'2330': {'kind': 'STOCK', 'name': '台積電'}}},
        'official:catalog:TWO': {'at': now, 'source': module.ENDPOINTS['TWO'],
                                 'scope': 'OFFICIAL_COMPANY_REGISTRY',
                                 'data': {'6488': {'kind': 'STOCK', 'name': '環球晶'}}},
    }
    writes = {}
    monkeypatch.setattr(module.time, 'time', lambda: now)
    monkeypatch.setattr(module, 'get', lambda key, default=None: docs.get(key, default))
    monkeypatch.setattr(module, 'put', lambda key, value: writes.__setitem__(key, value))
    summary = module._run_audit()
    assert summary['verified'] is True
    assert summary['stock_count'] == 2
    assert writes['v26:universe:verified_symbols']['symbols'] == ['2330.TW', '6488.TWO']
    assert writes['v26:universe:audit']['at'] == writes['v26:universe:verified_symbols']['at']


def test_missing_or_stale_registry_fails_closed(monkeypatch):
    now = 1000000.0
    docs = {
        'official:catalog:TW': {'at': now - module.CLASSIFICATION_TTL - 1,
                                'source': module.ENDPOINTS['TW'],
                                'scope': 'OFFICIAL_COMPANY_REGISTRY',
                                'data': {'2330': {'kind': 'STOCK', 'name': '台積電'}}}}
    writes = {}
    monkeypatch.setattr(module.time, 'time', lambda: now)
    monkeypatch.setattr(module, 'get', lambda key, default=None: docs.get(key, default))
    monkeypatch.setattr(module, 'put', lambda key, value: writes.__setitem__(key, value))
    summary = module._run_audit()
    assert summary['verified'] is False
    assert writes['v26:universe:verified_symbols']['symbols'] == []
