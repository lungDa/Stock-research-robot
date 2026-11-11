"""Persistent daily per-user, per-symbol AI quota reservations.

Only completed, distinct symbols consume a day's allowance. Concurrent callers
receive a pending result rather than launching duplicate model work.
"""
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import String, Integer, UniqueConstraint, select, func, update
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base, Session, Lease

TAIPEI=ZoneInfo("Asia/Taipei")

class AIUsage(Base):
    __tablename__="ai_daily_usage"
    id:Mapped[int]=mapped_column(primary_key=True)
    user:Mapped[str]=mapped_column(String(100),nullable=False,index=True)
    day:Mapped[str]=mapped_column(String(10),nullable=False)
    symbol:Mapped[str]=mapped_column(String(30),nullable=False)
    kind:Mapped[str]=mapped_column(String(12),nullable=False,default="normal")
    status:Mapped[str]=mapped_column(String(12),nullable=False,default="reserved")
    __table_args__=(UniqueConstraint("user","day","symbol","kind",name="unique_daily_ai_symbol"),)

def today():
    return datetime.now(TAIPEI).date().isoformat()

RESERVATION_TTL_SECONDS = 900

def _lease_key(user, day, symbol, kind):
    return f"ai-quota:{user}:{day}:{kind}:{symbol}"

def _clear_expired(s, user, day):
    # Called while holding the user's quota row lock.
    expired = s.scalars(select(AIUsage).where(
        AIUsage.user == user, AIUsage.day == day,
        AIUsage.status == "reserved")).all()
    for row in expired:
        lease = s.get(Lease, _lease_key(user, day, row.symbol, row.kind))
        if lease is None or lease.expires_at <= time.time():
            s.delete(row)
            if lease is not None:
                s.delete(lease)
    s.flush()

def usage(user,kind="normal"):
    from app.day_trader.access_models import UserAILimit
    day=today()
    with Session() as s:
        limits=s.get(UserAILimit,user)
        cap=(limits.emergency_daily_limit if kind=="emergency" else limits.normal_daily_limit) if limits else 0
        used=s.scalar(select(func.count()).select_from(AIUsage).where(
            AIUsage.user==user,AIUsage.day==day,AIUsage.kind==kind,AIUsage.status=="completed")) or 0
        pending=s.scalar(select(func.count()).select_from(AIUsage).where(
            AIUsage.user==user,AIUsage.day==day,AIUsage.kind==kind,AIUsage.status=="reserved")) or 0
        return {"date":day,"kind":kind,"limit":cap,"used":used,"pending":pending,
                "remaining":max(0,cap-used-pending)}

def reserve(user,symbol,kind="normal"):
    """PostgreSQL transaction serializes reservations per user via locked limit row.

    A missing configured limit fails closed. A previous completed symbol is free;
    a pending symbol must not launch another model call.
    """
    from app.day_trader.access_models import UserAILimit
    from sqlalchemy.exc import IntegrityError
    if kind not in ("normal","emergency"):raise ValueError("invalid quota kind")
    day=today()
    with Session.begin() as s:
        limit=s.scalar(select(UserAILimit).where(UserAILimit.user==user).with_for_update())
        if limit is None:return "no_limit_configured"
        cap=limit.emergency_daily_limit if kind=="emergency" else limit.normal_daily_limit
        _clear_expired(s, user, day)
        previous=s.scalar(select(AIUsage).where(AIUsage.user==user,AIUsage.day==day,
                                               AIUsage.symbol==symbol,AIUsage.kind==kind))
        if previous:return "cached" if previous.status=="completed" else "pending"
        count=s.scalar(select(func.count()).select_from(AIUsage).where(
            AIUsage.user==user,AIUsage.day==day,AIUsage.kind==kind,
            AIUsage.status.in_(("reserved","completed")))) or 0
        if count>=cap:return "exhausted"
        s.add(AIUsage(user=user,day=day,symbol=symbol,kind=kind,status="reserved"))
        s.add(Lease(key=_lease_key(user,day,symbol,kind),owner="quota",expires_at=time.time()+RESERVATION_TTL_SECONDS))
        return "reserved"

def finish(user,symbol,kind="normal",success=True,day=None):
    """Mark a reserved analysis completed, or release it on execution failure."""
    from sqlalchemy import delete
    day=day or today()
    with Session.begin() as s:
        criteria=(AIUsage.user==user,AIUsage.day==day,AIUsage.symbol==symbol,
                  AIUsage.kind==kind,AIUsage.status=="reserved")
        lease=s.get(Lease,_lease_key(user,day,symbol,kind))
        if lease is None or lease.expires_at <= time.time():
            return False
        if success:
            changed=bool(s.execute(update(AIUsage).where(*criteria).values(status="completed")).rowcount)
        else:
            changed=bool(s.execute(delete(AIUsage).where(*criteria)).rowcount)
        if changed:
            s.delete(lease)
        return changed
