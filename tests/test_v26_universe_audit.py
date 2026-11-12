from jobs.v26_universe_audit import audit

def test_verified_two_markets():
    markets = {m: {'complete': True, 'rows': [{'symbol': code + '.' + m}]}
               for m, code in [('TW', '2330'), ('TWO', '6488')]}
    quotes = {'2330.TW': {'kind': 'STOCK'}, '6488.TWO': {'kind': 'STOCK'}}
    result = audit(markets, quotes)
    assert result['verified'] is True
    assert result['market_counts'] == {'TW': 1, 'TWO': 1}

def test_unknown_classification_blocks_verification():
    markets = {'TW': {'complete': True, 'rows': [{'symbol': '2330.TW'}]},
               'TWO': {'complete': True, 'rows': [{'symbol': '6488.TWO'}]}}
    result = audit(markets, {'2330.TW': {'kind': 'STOCK'}})
    assert result['verified'] is False
    assert result['excluded']['UNKNOWN'] == 1

def test_partial_source_and_market_mismatch_fail_closed():
    markets = {'TW': {'complete': False, 'rows': [{'symbol': '6488.TWO'}]},
               'TWO': {'complete': True, 'rows': [{'symbol': '6488.TWO'}]}}
    assert not audit(markets, {'6488.TWO': {'kind': 'STOCK'}})['verified']
