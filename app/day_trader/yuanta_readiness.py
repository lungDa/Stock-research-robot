"""Yuanta SPARK onboarding gate; never stores secrets or places orders."""
from dataclasses import dataclass

@dataclass(frozen=True)
class YuantaReadiness:
    application_approved: bool = False
    market_data_entitled: bool = False
    trading_entitled: bool = False
    sdk_verified: bool = False
    runtime_verified: bool = False
    credentials_configured: bool = False
    live_trading_opt_in: bool = False

def assess(state: YuantaReadiness) -> dict:
    if not isinstance(state,YuantaReadiness):
        raise TypeError("state must be YuantaReadiness")
    data_ready=all((state.application_approved,state.market_data_entitled,
                    state.sdk_verified,state.runtime_verified,state.credentials_configured))
    # No real order path is implemented, even if a user has trading permission.
    return {
        "application_status":"approved" if state.application_approved else "pending",
        "market_data_ready":data_ready,
        "trading_permission_confirmed":state.application_approved and state.trading_entitled,
        "live_order_execution_enabled":False,
        "missing_market_data_prerequisites":[label for label,ready in (
            ("application_approved",state.application_approved),
            ("market_data_entitled",state.market_data_entitled),
            ("sdk_verified",state.sdk_verified),
            ("runtime_verified",state.runtime_verified),
            ("credentials_configured",state.credentials_configured)) if not ready],
        "note":"元大 SPARK 審核中；未確認 SDK、授權及環境前不可連線，且不啟用實盤交易。"
    }
