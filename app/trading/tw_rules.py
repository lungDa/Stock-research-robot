"""Taiwan paper-trading session and lot-size validation.

Only validates simulated order requests. POST_CLOSE and INTRADAY are
educational approximations, NOT exchange matching or broker day-trade approval.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Asia/Taipei")
MODES=("REGULAR","ODD_LOT","AFTER_HOURS","DAY_TRADE")

def validate_order_mode(mode, quantity, asset_type, now=None, enforce_hours=False):
    if mode not in MODES: raise ValueError("不支援的交易方式")
    if type(quantity) is not int or quantity < 1: raise ValueError("股數無效")
    if asset_type not in ("STOCK","ETF"): raise ValueError("商品類別無效")
    if mode in ("REGULAR","AFTER_HOURS","DAY_TRADE") and quantity % 1000:
        raise ValueError("此模式以1000股為單位；零股請選盤中零股")
    if mode=="ODD_LOT" and quantity >= 1000:
        raise ValueError("盤中零股每筆須為1至999股")
    if mode=="DAY_TRADE" and asset_type != "STOCK":
        raise ValueError("目前當沖模擬僅開放普通股票")
    if enforce_hours:
        local=(now or datetime.now(TZ)).astimezone(TZ)
        if local.weekday()>=5: raise ValueError("非一般交易日；休市日仍需交易所日曆核對")
        windows={"REGULAR":(time(9,0),time(13,30)),
                 "ODD_LOT":(time(9,0),time(13,30)),
                 "DAY_TRADE":(time(9,0),time(13,30)),
                 "AFTER_HOURS":(time(14,0),time(14,30))}
        start,end=windows[mode]
        if not start<=local.time()<end: raise ValueError("不在所選交易方式的模擬時段")
    return mode
