from app.day_trader.technical import score
from app.day_trader.ai_review import prepare_review

def sample():
    return [{"close":100+i*.1,"high":101+i*.1,"low":99+i*.1,"volume":1000}
            for i in range(60)]

def test_score_explainable_and_bounded():
    r=score(sample())
    assert r["complete"] is True
    assert 0<=r["score"]<=100
    assert sum(r["components"].values())==r["score"]

def test_missing_bars_not_filled():
    assert score(sample()[:59])["score"] is None
    assert score(sample()[:-1]+[{"close":float("nan"),"high":110,"low":100,"volume":1}])["complete"] is False

def test_ai_cannot_overwrite_score_or_trade():
    r=prepare_review("2330.TW",sample())
    assert r["ai_status"]=="NOT_CONFIGURED"
    assert r["score_mutable_by_ai"] is False
    assert r["order_execution_allowed"] is False
