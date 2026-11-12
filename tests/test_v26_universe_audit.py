from jobs.v26_universe_audit import audit

NOW = 1_800_000_000

def test_verified_two_markets():
    markets = {m: {'at': NOW, 'complete': True, 'rows': [{'symbol': code + '.' + m}]}
               for m, code in [('TW', '2330'), ('TWO', '6488')]}
    quotes = {'2330.TW': {'kind': 'STOCK'}, '6488.TWO': {'kind': 'STOCK'}}
    result = audit(markets, quotes, now=NOW)
    assert result['verified'] is True
    assert result['market_counts'] == {'TW': 1, 'TWO': 1}

def test_unknown_classification_blocks_verification():
    markets = {'TW': {'at': NOW, 'complete': True, 'rows': [{'symbol': '2330.TW'}]},
               'TWO': {'at': NOW, 'complete': True, 'rows': [{'symbol': '6488.TWO'}]}}
    result = audit(markets, {'2330.TW': {'kind': 'STOCK'}}, now=NOW)
    assert result['verified'] is False
    assert result['excluded']['UNKNOWN'] == 1

def test_partial_source_and_market_mismatch_fail_closed():
    markets = {'TW': {'at': NOW, 'complete': False, 'rows': [{'symbol': '6488.TWO'}]},
               'TWO': {'at': NOW, 'complete': True, 'rows': [{'symbol': '6488.TWO'}]}}
    assert not audit(markets, {'6488.TWO': {'kind': 'STOCK'}}, now=NOW)['verified']

def test_etf_excluded_without_false_failure():
    markets = {'TW': {'at': NOW, 'complete': True, 'rows': [
        {'symbol': '2330.TW'}, {'symbol': '0050.TW'}]},
        'TWO': {'at': NOW, 'complete': True, 'rows': [{'symbol': '6488.TWO'}]}}
    quotes = {'2330.TW': {'kind': 'STOCK'}, '0050.TW': {'kind': 'ETF'},
              '6488.TWO': {'kind': 'STOCK'}}
    result = audit(markets, quotes, now=NOW)
    assert result['verified'] and result['excluded']['ETF'] == 1
    assert result['stock_count'] == 2

def test_cross_market_duplicate_code():
    markets = {'TW': {'at': NOW, 'complete': True, 'rows': [{'symbol': '2330.TW'}]},
               'TWO': {'at': NOW, 'complete': True, 'rows': [{'symbol': '2330.TWO'}]}}
    quotes = {'2330.TW': {'kind': 'STOCK'}, '2330.TWO': {'kind': 'STOCK'}}
    assert not audit(markets, quotes, now=NOW)['verified']

def test_stale_universe_rejected():
    markets = {'TW': {'at': NOW - 9*86400, 'complete': True, 'rows': [{'symbol': '2330.TW'}]},
               'TWO': {'at': NOW, 'complete': True, 'rows': [{'symbol': '6488.TWO'}]}}
    quotes = {'2330.TW': {'kind': 'STOCK'}, '6488.TWO': {'kind': 'STOCK'}}
    assert not audit(markets, quotes, now=NOW)['verified']

def test_empty_universe_rejected():
    markets = {'TW': {'at': NOW, 'complete': True, 'rows': []},
               'TWO': {'at': NOW, 'complete': True, 'rows': []}}
    assert not audit(markets, {}, now=NOW)['verified']

def test_duplicate_symbol_rejected():
    markets = {'TW': {'at': NOW, 'complete': True, 'rows': [
        {'symbol': '2330.TW'}, {'symbol': '2330.TW'}]},
        'TWO': {'at': NOW, 'complete': True, 'rows': [{'symbol': '6488.TWO'}]}}
    quotes = {'2330.TW': {'kind': 'STOCK'}, '6488.TWO': {'kind': 'STOCK'}}
    assert not audit(markets, quotes, now=NOW)['verified']
