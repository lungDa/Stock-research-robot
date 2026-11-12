import pytest
from app.day_trader.ranking import rank_four_modes

def test_four_rankings_and_deterministic_order():
    rows=[
        {"symbol":"2330.TW","fundamental_score":90,"technical_score":60,
         "fundamental_complete":True,"technical_complete":True,"signal":"NO_SIGNAL"},
        {"symbol":"2317.TW","fundamental_score":60,"technical_score":95,
         "fundamental_complete":True,"technical_complete":True,"signal":"BREAKOUT_WATCH"},
    ]
    out=rank_four_modes(rows)
    assert out["rankings"]["long_term"][0]["symbol"]=="2330.TW"
    assert out["rankings"]["intraday"][0]["symbol"]=="2317.TW"
    assert out["rankings"]["combined"][0]["symbol"]=="2317.TW"
    assert all(not x["tradable"] for v in out["rankings"].values() for x in v)

def test_missing_and_stale_data_excluded_from_relevant_modes():
    rows=[
        {"symbol":"A","fundamental_score":80,"fundamental_complete":True},
        {"symbol":"B","technical_score":90,"technical_complete":True},
        {"symbol":"C","fundamental_score":99,"technical_score":99,
         "fundamental_complete":True,"technical_complete":True,"data_stale":True},
    ]
    out=rank_four_modes(rows)
    assert out["rankings"]["combined"]==[]
    assert [r["symbol"] for r in out["rankings"]["long_term"]]==["A"]
    assert [r["symbol"] for r in out["rankings"]["swing"]]==["B"]

def test_invalid_inputs_fail_closed():
    with pytest.raises(ValueError):rank_four_modes([{"symbol":"X"},{"symbol":"X"}])
    with pytest.raises(ValueError):rank_four_modes([],top_n=0)
    assert rank_four_modes([{"symbol":"X","technical_score":float("nan"),
                            "technical_complete":True}])["rankings"]["intraday"]==[]
