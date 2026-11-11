"""Deterministic paper fills. Caller-supplied prices are *not* real market executions."""
import re
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from app.db import Session
from app.trading.fees import PaperFeeSetting, fee_breakdown
from app.trading.models import (PaperAccount, PaperOrder, PaperExecution,
                                PaperPosition, PaperRiskLimit, PaperAllocation)

class PaperTradeRejected(ValueError): pass

def amount(value):
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d <= 0 or d.as_tuple().exponent < -4:
            raise PaperTradeRejected("價格必須為正且最多四位小數")
        return d
    except (InvalidOperation, TypeError):
        raise PaperTradeRejected("無效價格")

def create_account(user, starting_cash="1000000"):
    if not isinstance(user, str) or not user or len(user) > 100:
        raise PaperTradeRejected("使用者無效")
    cash = amount(starting_cash)
    with Session.begin() as s:
        if s.scalar(select(PaperAccount).where(PaperAccount.user == user)):
            raise PaperTradeRejected("模擬帳戶已存在")
        a = PaperAccount(user=user, initial_cash=cash, cash=cash)
        s.add(a); s.flush()
        s.add(PaperFeeSetting(account_id=a.id, mode='STANDARD', discount=Decimal('1'), minimum_fee=Decimal('20')))
        s.add(PaperRiskLimit(account_id=a.id, max_order_value=min(cash, Decimal("100000")),
                             max_position_value=min(cash, Decimal("200000"))))
        for name, pct in (("swing", "50"), ("intraday", "30"), ("reserve", "20")):
            s.add(PaperAllocation(account_id=a.id, strategy=name, percentage=Decimal(pct)))
        return a.id

def execute(user, client_order_id, symbol, side, quantity, price, asset_type='STOCK'):
    """Immediately settle one simulated fill, atomically and idempotently.

    SQLite serializes writes; PostgreSQL row lock protects account cash/positions.
    No market feed, broker, slippage, fees or settlement is represented here.
    """
    if not isinstance(client_order_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", client_order_id):
        raise PaperTradeRejected("委託識別碼無效")
    if not isinstance(symbol, str) or not re.fullmatch(r"[0-9]{4,6}(?:[.](?:TW|TWO))?", symbol):
        raise PaperTradeRejected("股票代號格式錯誤")
    if side not in ("BUY", "SELL") or type(quantity) is not int or not 1 <= quantity <= 1000000:
        raise PaperTradeRejected("買賣方向或股數無效")
    px = amount(price)
    if asset_type not in ('STOCK','ETF'): raise PaperTradeRejected('商品類別無效')
    with Session.begin() as s:
        a = s.scalar(select(PaperAccount).where(PaperAccount.user == user).with_for_update())
        if not a: raise PaperTradeRejected("模擬帳戶不存在")
        previous = s.scalar(select(PaperOrder).where(PaperOrder.account_id == a.id,
                              PaperOrder.client_order_id == client_order_id))
        if previous:
            if (previous.symbol, previous.side, previous.quantity, previous.price) != (symbol, side, quantity, px):
                raise PaperTradeRejected("重複委託識別碼內容不一致")
            return {"order_id": previous.id, "status": previous.status, "duplicate": True}
        if a.halted: raise PaperTradeRejected("模擬交易已緊急停止")
        limits = s.get(PaperRiskLimit, a.id)
        fee_config = s.get(PaperFeeSetting, a.id)
        if not fee_config: raise PaperTradeRejected('模擬費率設定不存在')
        try:
            fees = fee_breakdown(px, quantity, side, asset_type, fee_config.mode, fee_config.discount, fee_config.minimum_fee)
        except ValueError as exc: raise PaperTradeRejected(str(exc)) from exc
        value = px * quantity
        if not limits or value > limits.max_order_value: raise PaperTradeRejected("超過單筆交易上限")
        p = s.scalar(select(PaperPosition).where(PaperPosition.account_id == a.id,
                     PaperPosition.symbol == symbol).with_for_update())
        if side == "BUY":
            if -fees['net_cash'] > a.cash: raise PaperTradeRejected("模擬可用現金不足")
            old_qty = p.quantity if p else 0
            if (old_qty + quantity) * px > limits.max_position_value:
                raise PaperTradeRejected("超過單檔持倉上限")
            a.cash += fees['net_cash']
            if not p:
                p = PaperPosition(account_id=a.id, symbol=symbol, quantity=0, cost_basis=Decimal(0))
                s.add(p)
            p.cost_basis += value + fees['broker_fee']; p.quantity += quantity
        else:
            if not p or p.quantity < quantity: raise PaperTradeRejected("模擬庫存不足")
            average = p.cost_basis / p.quantity
            p.quantity -= quantity
            p.cost_basis = Decimal(0) if p.quantity == 0 else p.cost_basis - average * quantity
            a.cash += fees['net_cash']
        order = PaperOrder(account_id=a.id, client_order_id=client_order_id,
                           symbol=symbol, side=side, quantity=quantity, price=px, status="FILLED")
        s.add(order); s.flush()
        s.add(PaperExecution(order_id=order.id, quantity=quantity, price=px))
        return {"order_id": order.id, "status": "FILLED", "duplicate": False, "broker_fee":str(fees['broker_fee']),"transaction_tax":str(fees['transaction_tax']),"net_cash":str(fees['net_cash'])}

def snapshot(user):
    with Session() as s:
        a = s.scalar(select(PaperAccount).where(PaperAccount.user == user))
        if not a: raise PaperTradeRejected("模擬帳戶不存在")
        positions = s.scalars(select(PaperPosition).where(PaperPosition.account_id == a.id)).all()
        config=s.get(PaperFeeSetting,a.id)
        return {"cash": str(a.cash), "halted": a.halted,
                "fee_settings": {"mode":config.mode,"discount":str(config.discount),"minimum_fee":str(config.minimum_fee)} if config else None,
                "positions": [{"symbol": p.symbol, "quantity": p.quantity,
                               "cost_basis": str(p.cost_basis)} for p in positions]}

def halt(user):
    with Session.begin() as s:
        a = s.scalar(select(PaperAccount).where(PaperAccount.user == user).with_for_update())
        if not a: raise PaperTradeRejected("模擬帳戶不存在")
        a.halted = True

def update_fee_settings(user, mode, discount, minimum_fee):
    """Update one account's simulation commission policy only."""
    try:
        fee_breakdown(Decimal("100"), 1, "BUY", "STOCK", mode, discount, minimum_fee)
    except (ValueError, ArithmeticError) as exc: raise PaperTradeRejected(str(exc)) from exc
    with Session.begin() as s:
        a=s.scalar(select(PaperAccount).where(PaperAccount.user==user).with_for_update())
        if not a: raise PaperTradeRejected("模擬帳戶不存在")
        cfg=s.get(PaperFeeSetting,a.id)
        if not cfg: raise PaperTradeRejected("模擬費率設定不存在")
        cfg.mode=mode;cfg.discount=Decimal(str(discount));cfg.minimum_fee=Decimal(str(minimum_fee))
    return {"mode":mode,"discount":str(discount),"minimum_fee":str(minimum_fee)}
