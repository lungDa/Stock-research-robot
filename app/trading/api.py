"""Authenticated simulation-only API. No live broker routes."""
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.api.security import current_user
from app.trading.paper import create_account, execute, snapshot, halt, update_fee_settings, PaperTradeRejected

router = APIRouter(prefix="/paper", tags=["paper trading"])

class AccountInput(BaseModel):
    starting_cash: Decimal = Field(default=Decimal("1000000"), gt=0, le=100000000)

class OrderInput(BaseModel):
    client_order_id: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=4, max_length=30)
    side: str = Field(pattern=r"^(BUY|SELL)$")
    quantity: int = Field(gt=0, le=1000000)
    price: Decimal = Field(gt=0)
    asset_type: str = Field(default="STOCK", pattern=r"^(STOCK|ETF)$")
    order_mode: str = Field(default="REGULAR", pattern=r"^(REGULAR|ODD_LOT|AFTER_HOURS|DAY_TRADE)$")

class FeeInput(BaseModel):
    mode: str = Field(pattern=r"^(STANDARD|CUSTOM)$")
    discount: Decimal = Field(default=Decimal("1"), gt=0, le=1)
    minimum_fee: Decimal = Field(default=Decimal("20"), ge=0, le=10000)

def reject(exc):
    raise HTTPException(status_code=400, detail=str(exc))

@router.post("/account", status_code=201)
def open_account(body: AccountInput, user=Depends(current_user)):
    try:
        return {"account_id": create_account(user, body.starting_cash), "mode": "PAPER"}
    except PaperTradeRejected as exc:
        reject(exc)

@router.get("/account")
def account(user=Depends(current_user)):
    try:
        return {**snapshot(user), "mode": "PAPER"}
    except PaperTradeRejected as exc:
        reject(exc)

@router.post("/orders")
def place_order(body: OrderInput, user=Depends(current_user)):
    try:
        result = execute(user, body.client_order_id, body.symbol, body.side,
                         body.quantity, body.price, body.asset_type, body.order_mode)
        return {**result, "mode": "PAPER"}
    except PaperTradeRejected as exc:
        reject(exc)

@router.post("/halt")
def emergency_stop(user=Depends(current_user)):
    try:
        halt(user)
        return {"halted": True, "mode": "PAPER"}
    except PaperTradeRejected as exc:
        reject(exc)

@router.put("/fees")
def set_fees(body: FeeInput, user=Depends(current_user)):
    try:
        return {**update_fee_settings(user, body.mode, body.discount, body.minimum_fee),
                "mode_type": "PAPER"}
    except PaperTradeRejected as exc:
        reject(exc)
