from app.day_trader.yuanta_readiness import YuantaReadiness,assess

def test_pending_application_blocks_data_and_trades():
    result=assess(YuantaReadiness())
    assert result["application_status"]=="pending"
    assert result["market_data_ready"] is False
    assert result["live_order_execution_enabled"] is False

def test_approval_does_not_automatically_enable_trading():
    result=assess(YuantaReadiness(True,True,True,True,True,True,True))
    assert result["market_data_ready"] is True
    assert result["trading_permission_confirmed"] is True
    assert result["live_order_execution_enabled"] is False
