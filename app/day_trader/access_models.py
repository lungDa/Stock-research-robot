"""V2.5 stage 1: database schema for a single administrator and per-user AI limits.

Schema only. No user is granted administrator privileges by creating these tables.
All privilege checks must be implemented server-side before exposing write endpoints.
"""
from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

class AdminBootstrap(Base):
    __tablename__ = "ai_admin_bootstrap"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    designated_user: Mapped[str] = mapped_column(String(100), nullable=False)
    designated_line_user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    initialized_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (CheckConstraint("id = 1", name="one_admin_bootstrap_row"),)

class UserAILimit(Base):
    __tablename__ = "ai_user_limits"
    user: Mapped[str] = mapped_column(String(100), primary_key=True)
    normal_daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emergency_daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        CheckConstraint("normal_daily_limit >= 0", name="normal_limit_nonnegative"),
        CheckConstraint("emergency_daily_limit >= 0", name="emergency_limit_nonnegative"),
    )

class EmergencyAIRequest(Base):
    __tablename__ = "ai_emergency_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    requested_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(timezone.utc))
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    __table_args__ = (CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','EXECUTED','FAILED')", name="valid_emergency_status"),)
