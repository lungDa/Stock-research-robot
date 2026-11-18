"""Isolated simulation tests: never sends orders to a real broker."""
import pytest
from app.trading.paper import create_account, execute, snapshot, halt, PaperTradeRejected
from app.db import Session
from app.trading.models import PaperOrder, PaperExecution, PaperAllocation
from sqlalchemy import select

def test_buy_sell_and_duplicate_idempotency():
    create_account("alice")
    buy = execute("alice", "order-1", "2330.TW", "BUY", 100, "500", order_mode="ODD_LOT")
    assert buy["status"] == "FILLED"
    assert execute("alice", "order-1", "2330.TW", "BUY", 100, "500", order_mode="ODD_LOT")["duplicate"]
    with pytest.raises(PaperTradeRejected):
        execute("alice", "order-1", "2330.TW", "BUY", 200, "500", order_mode="ODD_LOT")
    assert snapshot("alice")["positions"][0]["quantity"] == 100
    assert snapshot("alice")["cash"] == "949929.0000"
    execute("alice", "order-2", "2330.TW", "SELL", 40, "600", order_mode="ODD_LOT")
    assert snapshot("alice")["positions"][0]["quantity"] == 60
    assert snapshot("alice")["cash"] == "973823.0000"
    with Session() as s:
        assert len(s.scalars(select(PaperOrder)).all()) == 2
        assert len(s.scalars(select(PaperExecution)).all()) == 2

def test_tenant_isolation_and_limits():
    create_account("alice"); create_account("bob")
    execute("alice", "buy1", "0050.TW", "BUY", 100, "100", order_mode="ODD_LOT")
    assert snapshot("bob")["positions"] == []
    for args in [("big", "0050.TW", "BUY", 2000, "100"),
                 ("short", "0050.TW", "SELL", 200, "100")]:
        with pytest.raises(PaperTradeRejected): execute("alice", *args, order_mode="ODD_LOT")
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


def test_symbol_aliases_share_inventory_and_risk_limit():
    create_account('alice')
    execute('alice','a','2330','BUY',500,'200',order_mode='ODD_LOT')
    execute('alice','b',' 2330.tw ','BUY',500,'200',order_mode='ODD_LOT')
    with pytest.raises(PaperTradeRejected,match='持倉上限'):
        execute('alice','c','2330','BUY',1,'200',order_mode='ODD_LOT')
    execute('alice','d','2330.TW','SELL',1,'200',order_mode='ODD_LOT')
    assert snapshot('alice')['positions'][0]['quantity']==999
    assert len(snapshot('alice')['positions'])==1


def test_retry_preserves_original_fees_and_checks_full_identity():
    from app.trading.paper import update_fee_settings
    create_account('alice')
    first=execute('alice','a','0050','BUY',10,'100',asset_type='ETF',order_mode='ODD_LOT')
    update_fee_settings('alice','CUSTOM','0.5','1')
    retry=execute('alice','a','0050.TW','BUY',10,'100',asset_type='ETF',order_mode='ODD_LOT')
    from decimal import Decimal
    assert Decimal(first['broker_fee'])==Decimal(retry['broker_fee'])
    with pytest.raises(PaperTradeRejected,match='商品類別'):
        execute('alice','a','0050','BUY',10,'100',order_mode='ODD_LOT')
    assert len(snapshot('alice')['recent_orders'])==1
    create_account('bob')
    assert snapshot('bob')['recent_orders']==[]


def test_legacy_aliases_consolidate_without_changing_cost():
    from app.trading.models import PaperAccount, PaperPosition
    from decimal import Decimal
    create_account('alice')
    with Session.begin() as s:
        account=s.scalar(select(PaperAccount).where(PaperAccount.user=='alice'))
        s.add_all([PaperPosition(account_id=account.id,symbol='2330',quantity=100,cost_basis=Decimal('10000')),
                   PaperPosition(account_id=account.id,symbol='2330.TW',quantity=100,cost_basis=Decimal('12000'))])
    execute('alice','sell','2330','SELL',100,'100',order_mode='ODD_LOT')
    positions=snapshot('alice')['positions']
    assert len(positions)==1
    assert positions[0]['quantity']==100
    assert Decimal(positions[0]['cost_basis'])==Decimal('11000')


def test_additive_upgrade_preserves_existing_ledger():
    from app.db import init_db,engine
    from app.trading.models import PaperOrderDetail
    create_account('alice')
    execute('alice','old','2330','BUY',100,'100',order_mode='ODD_LOT')
    cash=snapshot('alice')['cash']
    # Simulate the pre-upgrade schema: orders exist without the new detail table.
    PaperOrderDetail.__table__.drop(engine)
    init_db()
    assert snapshot('alice')['cash']==cash
    assert snapshot('alice')['recent_orders'][0]['legacy_details_unavailable']
    duplicate=execute('alice','old','2330.TW','BUY',100,'100',order_mode='ODD_LOT')
    assert duplicate['duplicate'] and duplicate['legacy_details_unavailable']
    assert snapshot('alice')['cash']==cash


def test_retry_different_mode_is_rejected_even_with_same_cash_amount():
    create_account('alice')
    execute('alice','mode','2330','BUY',1000,'50')
    with pytest.raises(PaperTradeRejected,match='交易方式'):
        execute('alice','mode','2330','BUY',1000,'50',order_mode='AFTER_HOURS')
