"""Daily quota state machine: one completed symbol per Taipei day."""
from app.db import Session
from app.day_trader.access_models import UserAILimit
from app.day_trader.ai_usage import reserve, finish, usage

def test_daily_quota_reserve_complete_and_reuse():
    user="U"+"4"*32
    with Session.begin() as db:
        db.merge(UserAILimit(user=user,normal_daily_limit=1,emergency_daily_limit=1))
    assert reserve(user,"2330.TW")=="reserved"
    assert reserve(user,"2330.TW")=="pending"
    assert usage(user)["remaining"]==0
    assert reserve(user,"2412.TW")=="exhausted"
    assert finish(user,"2330.TW")
    assert reserve(user,"2330.TW")=="cached"
    assert usage(user)["used"]==1
    assert usage(user)["remaining"]==0
    assert reserve(user,"2412.TW","emergency")=="reserved"
    assert usage(user,"emergency")["pending"]==1

def test_failed_analysis_releases_reservation():
    user="U"+"3"*32
    with Session.begin() as db:
        db.merge(UserAILimit(user=user,normal_daily_limit=1,emergency_daily_limit=0))
    assert reserve(user,"2303.TW")=="reserved"
    assert finish(user,"2303.TW",success=False)
    assert usage(user)["remaining"]==1
    assert reserve(user,"2303.TW")=="reserved"

def test_unconfigured_user_is_denied():
    assert reserve("U"+"2"*32,"2330.TW")=="no_limit_configured"
