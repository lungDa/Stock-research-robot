import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from app.trading.tw_rules import validate_order_mode

def test_trade_modes_and_lots():
    assert validate_order_mode("REGULAR",1000,"STOCK")=="REGULAR"
    assert validate_order_mode("ODD_LOT",1,"ETF")=="ODD_LOT"
    assert validate_order_mode("AFTER_HOURS",2000,"STOCK")=="AFTER_HOURS"
    assert validate_order_mode("DAY_TRADE",1000,"STOCK")=="DAY_TRADE"
    for mode,qty,asset in [("REGULAR",100,"STOCK"),("ODD_LOT",1000,"ETF"),
                           ("AFTER_HOURS",999,"STOCK"),("DAY_TRADE",1000,"ETF"),
                           ("UNKNOWN",1000,"STOCK")]:
        with pytest.raises(ValueError):
            validate_order_mode(mode,qty,asset)

def test_simulation_hours_are_optional_and_explicit():
    tz=ZoneInfo("Asia/Taipei")
    with pytest.raises(ValueError):
        validate_order_mode("REGULAR",1000,"STOCK",now=datetime(2026,11,11,8,0,tzinfo=tz),enforce_hours=True)
    assert validate_order_mode("REGULAR",1000,"STOCK",now=datetime(2026,11,11,8,0,tzinfo=tz))=="REGULAR"
