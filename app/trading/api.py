"""Authenticated, simulation-only endpoints. Never connect to a broker."""
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.api.security import current_user
from app.trading.paper import (create_account, execute, snapshot, halt, PaperTradeRejected)

router = APIRouter(prefix="/paper", tags=["paper trading"])

class AccountInput(BaseModel):
    starting_cash: Decimal = Field(default=Decimal("1000000"), gt=0, le=Decimal("100000000"))

class OrderInput(BaseModel):
    client_order_id: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=4, max_length=30)
    side: str
    quantity: int = Field(gt=0, le=1000000)
    price: Decimal = Field(gt=0)

def reject(exc):
    raise HTTPException(status_code=400, detail=str(exc))

@router.post("/account", status_code=201)
def open_account(body: AccountInput, user=Depends(current_user)):
    try:
        return {"account_id": create_account(user, body.starting_cash), "mode": "PAPER"}
    except PaperTradeRejected as exc: reject(exc)

@router.get("/account")
def account(user=Depends(current_user)):
    try: return {**snapshot(user), "mode": "PAPER"}
    except PaperTradeRejected as exc: reject(exc)

@router.post("/orders")
def place_order(body: OrderInput, user=Depends(current_user)):
    try:
        return {**execute(user, body.client_order_id, body.symbol,
                          body.side, body.quantity, body.price), "mode": "PAPER"}
    except PaperTradeRejected as exc: reject(exc)

@router.post("/halt")
def emergency_stop(user=Depends(current_user)):
    try: halt(user); return {"halted": True, "mode": "PAPER"}
    except PaperTradeRejected as exc: reject(exc)
