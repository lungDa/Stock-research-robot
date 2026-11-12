"""Device-scoped LINE sessions. Server-side records; no client-controlled session IDs."""
import time
from sqlalchemy import Boolean, Float, String, select, update
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base, Session

class LoginDevice(Base):
    __tablename__ = "login_devices"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_seen: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

def register(session_id, user, expires_at):
    now = time.time()
    with Session.begin() as db:
        db.add(LoginDevice(session_id=session_id, user=user, created_at=now,
                           last_seen=now, expires_at=expires_at, revoked=False))

def permitted(session_id):
    with Session() as db:
        row = db.get(LoginDevice, session_id)
        return bool(row and not row.revoked and row.expires_at > time.time())

def touch(session_id):
    with Session.begin() as db:
        db.execute(update(LoginDevice).where(LoginDevice.session_id == session_id,
            LoginDevice.revoked.is_(False)).values(last_seen=time.time()))

def extend(session_id, expires_at):
    with Session.begin() as db:
        db.execute(update(LoginDevice).where(LoginDevice.session_id == session_id,
            LoginDevice.revoked.is_(False)).values(expires_at=expires_at))

def revoke(session_id, user):
    with Session.begin() as db:
        return bool(db.execute(update(LoginDevice).where(LoginDevice.session_id == session_id,
            LoginDevice.user == user, LoginDevice.revoked.is_(False)).values(revoked=True)).rowcount)

def revoke_others(user, current_id):
    with Session.begin() as db:
        return db.execute(update(LoginDevice).where(LoginDevice.user == user,
            LoginDevice.session_id != current_id, LoginDevice.revoked.is_(False))
            .values(revoked=True)).rowcount

def list_devices(user, current_id):
    with Session() as db:
        rows = db.scalars(select(LoginDevice).where(LoginDevice.user == user,
            LoginDevice.expires_at > time.time()).order_by(LoginDevice.created_at.desc()).limit(100)).all()
        return [{"session_id": row.session_id, "created_at": row.created_at,
                 "last_seen": row.last_seen, "current": row.session_id == current_id,
                 "revoked": row.revoked} for row in rows]
