"""Crash recovery of abandoned daily AI quota reservations."""
import time
from sqlalchemy import select, update
from app.db import Session, Lease
from app.day_trader.access_models import UserAILimit
from app.day_trader.ai_usage import reserve, usage, finish, today, _lease_key

def test_expired_reservation_releases_capacity():
    user="U"+"6"*32
    with Session.begin() as s:
        s.merge(UserAILimit(user=user,normal_daily_limit=1,emergency_daily_limit=0))
    assert reserve(user,"2330.TW")=="reserved"
    with Session.begin() as s:
        s.execute(update(Lease).where(Lease.key==_lease_key(user,today(),"2330.TW","normal")).values(expires_at=time.time()-1))
    assert usage(user)["remaining"]==1
    assert reserve(user,"2412.TW")=="reserved"
    assert finish(user,"2412.TW",success=False)

def test_expired_reservation_cannot_complete():
    user="U"+"7"*32
    with Session.begin() as s:
        s.merge(UserAILimit(user=user,normal_daily_limit=1,emergency_daily_limit=0))
    assert reserve(user,"2330.TW")=="reserved"
    with Session.begin() as s:
        s.execute(update(Lease).where(Lease.key==_lease_key(user,today(),"2330.TW","normal")).values(expires_at=time.time()-1))
    assert finish(user,"2330.TW",success=True) is False
    assert reserve(user,"2412.TW")=="reserved"
