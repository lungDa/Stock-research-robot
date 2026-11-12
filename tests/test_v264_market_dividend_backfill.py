from jobs.v264_market_dividend_backfill import verified_symbols


def snapshot(now=1000):
    return ({'verified': True, 'at': now,
             'symbols': ['2330.TW', '2317.TW', '6488.TWO']},
            {'verified': True, 'at': now, 'stock_count': 3,
             'scope': 'TW_TWO_ORDINARY_STOCKS'})


def test_verified_snapshot_accepted():
    a, b = snapshot()
    assert verified_symbols(a, b, now=1001) == ['2317.TW', '2330.TW', '6488.TWO']


def test_unverified_snapshot_rejected():
    a, b = snapshot()
    a['verified'] = False
    assert verified_symbols(a, b, now=1001) == []


def test_stale_snapshot_rejected():
    a, b = snapshot()
    assert verified_symbols(a, b, now=1000 + 9 * 86400) == []


def test_mismatched_snapshot_rejected():
    a, b = snapshot()
    b['stock_count'] = 4
    assert verified_symbols(a, b, now=1001) == []


def test_duplicate_symbol_rejected():
    a, b = snapshot()
    a['symbols'][2] = '2330.TW'
    assert verified_symbols(a, b, now=1001) == []
