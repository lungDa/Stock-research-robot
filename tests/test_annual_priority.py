from app.services.annual_priority import choose_market_batch


def test_priority_and_rotation_share_batch():
    universe=[f'{i:04d}.TW' for i in range(1000,1020)]
    snapshot={'at':100,'scope':'THREE_FIELD_DIAGNOSTIC',
              'symbols':universe[10:16]}
    selected,advance=choose_market_batch(universe,0,snapshot,now=100)
    assert len(selected)==12
    assert selected[:6]==universe[10:16]
    assert selected[6:]==universe[:6]
    assert advance==6


def test_stale_snapshot_uses_only_market_rotation():
    universe=[f'{i:04d}.TW' for i in range(1000,1020)]
    snapshot={'at':0,'scope':'THREE_FIELD_DIAGNOSTIC','symbols':universe[10:16]}
    selected,advance=choose_market_batch(universe,3,snapshot,now=200000)
    assert selected==universe[3:15]
    assert advance==12


def test_overlap_deduplicates_and_preserves_rotation():
    universe=[f'{i:04d}.TW' for i in range(1000,1020)]
    snapshot={'at':100,'scope':'THREE_FIELD_DIAGNOSTIC',
              'symbols':universe[:6]+['9999.TW',universe[0]]}
    selected,advance=choose_market_batch(universe,0,snapshot,now=100)
    assert len(selected)==12
    assert len(set(selected))==12
    assert advance==12


def test_empty_market():
    assert choose_market_batch([],0,{},now=100)==([],0)
