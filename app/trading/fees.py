"""Per-user simulation fee settings. Percentages are decimals, not percentages.
Trading-tax rates are configurable assumptions; check current exchange rules.
"""
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import String, Numeric, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

STANDARD_BROKER_RATE = Decimal("0.001425")
DEFAULT_MINIMUM_FEE = Decimal("20")
STOCK_SELL_TAX = Decimal("0.003")
ETF_SELL_TAX = Decimal("0.001")

class PaperFeeSetting(Base):
    __tablename__ = "paper_fee_settings"
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="STANDARD")
    discount: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("1"))
    minimum_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=DEFAULT_MINIMUM_FEE)
    __table_args__ = (
        CheckConstraint("mode IN ('STANDARD','CUSTOM')"),
        CheckConstraint("discount > 0 AND discount <= 1"),
        CheckConstraint("minimum_fee >= 0"),
    )

def fee_breakdown(price, quantity, side, asset_type, mode="STANDARD", discount="1", minimum_fee="20"):
    if asset_type not in ("STOCK", "ETF"): raise ValueError("商品類別必須為 STOCK 或 ETF")
    if side not in ("BUY", "SELL"): raise ValueError("交易方向錯誤")
    if mode not in ("STANDARD", "CUSTOM"): raise ValueError("費率模式錯誤")
    d=Decimal(str(discount)); floor=Decimal(str(minimum_fee))
    if not d.is_finite() or not Decimal("0") < d <= Decimal("1"): raise ValueError("折扣倍率須大於0且不超過1")
    if not floor.is_finite() or not Decimal("0") <= floor <= Decimal("10000"): raise ValueError("最低手續費無效")
    gross=Decimal(str(price))*quantity
    rate=STANDARD_BROKER_RATE*(Decimal("1") if mode=="STANDARD" else d)
    broker=max(floor, (gross*rate).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    tax_rate=STOCK_SELL_TAX if asset_type=="STOCK" else ETF_SELL_TAX
    tax=(gross*tax_rate).quantize(Decimal("1"),rounding=ROUND_HALF_UP) if side=="SELL" else Decimal(0)
    return {"gross":gross,"broker_fee":broker,"transaction_tax":tax,"net_cash":(-gross-broker if side=="BUY" else gross-broker-tax)}
