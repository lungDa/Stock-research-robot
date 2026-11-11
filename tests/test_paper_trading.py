"""Isolated simulation tests: never sends orders to a real broker."""
import pytest
from app.trading.paper import create_account, execute, snapshot, halt, PaperTradeRejected
from app.db import Session
from app.trading.models import PaperOrder, PaperExecution, PaperAllocation
from sqlalchemy import select

def test_buy_sell_and_duplicate_idempotency():
    create_account("alice")
    buy = execute("alice", "order-1", "2330.TW", "BUY", 100, "500")
    assert buy["status"] == "FILLED"
    assert execute("alice", "order-1", "2330.TW", "BUY", 100, "500")["duplicate"]
    with pytest.raises(PaperTradeRejected):
        execute("alice", "order-1", "2330.TW", "BUY", 200, "500")
    assert snapshot("alice")["positions"][0]["quantity"] == 100
    assert snapshot("alice")["cash"] == "949929.0000"
    execute("alice", "order-2", "2330.TW", "SELL", 40, "600")
    assert snapshot("alice")["positions"][0]["quantity"] == 60
    assert snapshot("alice")["cash"] == "973823.0000"
    with Session() as s:
        assert len(s.scalars(select(PaperOrder)).all()) == 2
        assert len(s.scalars(select(PaperExecution)).all()) == 2

def test_tenant_isolation_and_limits():
    create_account("alice"); create_account("bob")
    execute("alice", "buy1", "0050.TW", "BUY", 100, "100")
    assert snapshot("bob")["positions"] == []
    for args in [("big", "0050.TW", "BUY", 2000, "100"),
                 ("short", "0050.TW", "SELL", 200, "100")]:
        with pytest.raises(PaperTradeRejected): execute("alice", *args)
    assert snapshot("alice")["cash"] == "989980.0000"

def test_halt_and_validation():
    create_account("alice")
    for qty, px in [(0, "100"), (True, "100"), (1, "NaN"), (1, "-1"), (1, "1.00001")]:
        with pytest.raises(PaperTradeRejected):
            execute("alice", "x", "2330.TW", "BUY", qty, px)
    halt("alice")
    with pytest.raises(PaperTradeRejected):
        execute("alice", "halted", "2330.TW", "BUY", 1, "100")

def test_default_allocation_sums_to_100():
    create_account("alice")
    with Session() as s:
        rows=s.scalars(select(PaperAllocation)).all()
        assert sum(row.percentage for row in rows) == 100
