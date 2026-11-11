"""Best-effort administrator login security alerts.

Every newly authenticated LINE session is treated as an unrecognized session until
a separate trusted-device protocol is implemented. Do not claim fingerprint certainty.
"""
import logging
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

def notify_admin_login(user: str, session_id: str) -> bool:
    from app.day_trader.admin_bootstrap import admin_identity_matches
    if not admin_identity_matches(user):
        return False
    from app.channels import line
    timestamp = datetime.now(timezone.utc).astimezone(
        ZoneInfo("Asia/Taipei")).strftime("%Y/%m/%d %H:%M:%S")
    message = (
        "🔐 股海燈塔｜新的管理員登入工作階段\n"
        f"時間：{timestamp}（台灣時間）\n"
        "已完成 LINE Login 與平台密碼驗證。\n"
        "系統目前尚未建立可信任裝置辨識，因此每次新的登入工作階段都會提醒。\n"
        "如果不是本人操作，請立即前往安全管理中心撤銷可疑工作階段。"
    )
    try:
        line.push(user, message, secrets.token_hex(16))
        return True
    except Exception:
        # Notification must not leak session credentials or crash the auth endpoint.
        log.exception("Administrator login alert delivery failed (session=%s)", session_id[:12])
        return False
