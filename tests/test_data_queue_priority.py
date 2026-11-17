from app.services.data_queue import prioritize_missing


def test_fewest_missing_fields_first():
    rows=[
        {'symbol':'2330.TW','missing_fields':4,'requested_at':100},
        {'symbol':'2412.TW','missing_fields':1,'requested_at':100},
        {'symbol':'2303.TW','missing_fields':2,'requested_at':100},
    ]
    assert [x['symbol'] for x in prioritize_missing(rows,now=100)]==[
        '2412.TW','2303.TW','2330.TW']


def test_old_request_eventually_moves_ahead():
    rows=[
        {'symbol':'old.TW','missing_fields':5,'requested_at':0},
        {'symbol':'new.TW','missing_fields':1,'requested_at':20*86400},
    ]
    assert prioritize_missing(rows,now=20*86400)[0]['symbol']=='old.TW'


def test_duplicates_invalid_rows_and_stable_order():
    rows=[
        {'symbol':'B.TW','missing_fields':2,'requested_at':10},
        {'symbol':'B.TW','missing_fields':1,'requested_at':20},
        {'symbol':'A.TW','missing_fields':1,'requested_at':20},
        {'symbol':'bad.TW','missing_fields':-1,'requested_at':20},
        {'symbol':'nan.TW','missing_fields':1,'requested_at':float('nan')},
    ]
    assert [x['symbol'] for x in prioritize_missing(rows,now=20)]==['A.TW','B.TW']
