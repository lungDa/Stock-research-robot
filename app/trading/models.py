"""Dedicated, tenant-scoped paper trading ledger; no live broker credentials."""
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Numeric, Integer, ForeignKey, UniqueConstraint, CheckConstraint, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

def utcnow(): return datetime.now(timezone.utc)

class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    halted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (CheckConstraint("cash >= 0"),)

class PaperOrder(Base):
    __tablename__ = "paper_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), nullable=False, index=True)
    client_order_id: Mapped[str] = mapped_column(String(80), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("account_id", "client_order_id"),
                      CheckConstraint("quantity > 0"), CheckConstraint("price > 0"),
                      CheckConstraint("side IN ('BUY', 'SELL')"))

class PaperExecution(Base):
    __tablename__ = "paper_executions"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("paper_orders.id"), nullable=False, unique=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class PaperPosition(Base):
    __tablename__ = "paper_positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, nullable=False)
    __table_args__ = (UniqueConstraint("account_id", "symbol"), CheckConstraint("quantity >= 0"),)

class PaperRiskLimit(Base):
    __tablename__ = "paper_risk_limits"
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), primary_key=True)
    max_order_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    max_position_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    __table_args__ = (CheckConstraint("max_order_value > 0"), CheckConstraint("max_position_value > 0"),)

class PaperAllocation(Base):
    __tablename__ = "paper_allocations"
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), primary_key=True)
    strategy: Mapped[str] = mapped_column(String(30), primary_key=True)
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    __table_args__ = (CheckConstraint("percentage >= 0 AND percentage <= 100"),)
