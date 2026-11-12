"""V2.5 stage 2: fail-closed admin identity and one-time LINE challenge.

Provisioning is deliberately NOT a public endpoint. A trusted operator must first
designate the existing verified LINE identity in AdminBootstrap (id=1).
"""
import hashlib
import hmac
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from sqlalchemy import update
from app.db import Session
from app.day_trader.access_models import AdminBootstrap
from app.channels import line

OTP_TTL_SECONDS = 300
MAX_ATTEMPTS = 5

def _valid_line_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"U[0-9a-fA-F]{32}", value))

def _hash_otp(otp, salt):
    return hashlib.sha256((salt + ":" + otp).encode()).hexdigest()

def _record():
    with Session() as session:
        row = session.get(AdminBootstrap, 1)
        if row is None:
            return None
        return {"user": row.designated_user, "line_id": row.designated_line_user_id,
                "initialized": bool(row.initialized)}

def admin_identity_matches(user):
    """Only previously initialized, dual-bound identities can be administrators."""
    row = _record()
    return bool(row and row["initialized"] and _valid_line_id(user)
                and hmac.compare_digest(row["user"], user)
                and hmac.compare_digest(row["line_id"], user))

def issue_initialization_otp(user):
    """Send OTP only to the predesignated LINE identity; never to user-supplied recipient."""
    row = _record()
    if not row or row["initialized"] or not _valid_line_id(user):
        raise PermissionError("初始化不可用")
    if not (hmac.compare_digest(row["user"], user) and
            hmac.compare_digest(row["line_id"], user)):
        raise PermissionError("不是預先指定的管理員")
    from app.db import acquire_lease, release_lease, get, put
    lease = acquire_lease("admin:bootstrap:otp:lock", seconds=20)
    if not lease:
        raise PermissionError("驗證程序忙碌")
    try:
        current = get("admin:bootstrap:otp", {})
        if current.get("expires", 0) > time.time():
            raise PermissionError("驗證碼已發送，請稍後重試")
        otp = f"{secrets.randbelow(1000000):06d}"
        salt = secrets.token_hex(16)
        # Write before sending: if delivery fails, no valid OTP is exposed to caller.
        put("admin:bootstrap:otp", {"digest": _hash_otp(otp, salt), "salt": salt,
            "expires": time.time() + OTP_TTL_SECONDS, "attempts": 0, "user": user})
        try:
            line.push(row["line_id"], "股海燈塔管理員初始化驗證碼：" + otp +
                      "（5分鐘內有效，請勿轉傳）", str(uuid.uuid4()))
        except Exception:
            # Failed delivery must not leave a live challenge that blocks retries.
            put("admin:bootstrap:otp", {"expires": 0, "attempts": MAX_ATTEMPTS})
            raise
    finally:
        release_lease("admin:bootstrap:otp:lock", lease)
    return {"sent": True, "expires_in": OTP_TTL_SECONDS}

def verify_initialization_otp(user, otp):
    """Atomic lock and single-use initialization; OTP is never returned to caller."""
    from app.db import acquire_lease, release_lease, get, put
    if not _valid_line_id(user) or not isinstance(otp, str) or not re.fullmatch(r"[0-9]{6}", otp):
        return False
    lease = acquire_lease("admin:bootstrap:otp:lock", seconds=20)
    if not lease:
        return False
    try:
        challenge = get("admin:bootstrap:otp", {})
        if (challenge.get("expires", 0) <= time.time() or
            challenge.get("attempts", MAX_ATTEMPTS) >= MAX_ATTEMPTS or
            challenge.get("user") != user):
            return False
        challenge["attempts"] += 1
        if not hmac.compare_digest(challenge.get("digest", ""),
                                   _hash_otp(otp, challenge.get("salt", ""))):
            put("admin:bootstrap:otp", challenge)
            return False
        with Session.begin() as session:
            changed = session.execute(
                update(AdminBootstrap).where(
                    AdminBootstrap.id == 1,
                    AdminBootstrap.initialized.is_(False),
                    AdminBootstrap.designated_user == user,
                    AdminBootstrap.designated_line_user_id == user
                ).values(initialized=True, initialized_at=datetime.now(timezone.utc))
            ).rowcount
        if changed != 1:
            return False
        put("admin:bootstrap:otp", {"expires": 0, "attempts": MAX_ATTEMPTS})
        return True
    finally:
        release_lease("admin:bootstrap:otp:lock", lease)


def _eligible_bootstrap_member(member):
    """Accept verified legacy accounts without activation_pending, never pending accounts."""
    if not isinstance(member, dict):
        return False
    if member.get("active") is not True or not isinstance(member.get("password_hash"), str):
        return False
    if not member["password_hash"].startswith("scrypt$") or member.get("password_change_required") is not False:
        return False
    if member.get("activation_pending") is True:
        return False
    if "activation_pending" in member:
        return member["activation_pending"] is False
    # Older active accounts did not persist activation_pending. A rotated
    # password_version is required in addition to the completed password state.
    return bool(member.get("password_version"))


def provision_designated_admin_from_env():
    """Idempotent, fail-closed provisioning from Render env after DB initialization.

    Never changes an existing designation, even if the env variable changes.
    Provisioning is not activation: LINE OTP must still be verified.
    """
    import os
    from sqlalchemy.exc import IntegrityError
    from app.db import get
    designated = os.getenv("LIGHTHOUSE_BOOTSTRAP_ADMIN_LINE_USER_ID", "").strip()
    if not designated:
        return "not_configured"
    if not _valid_line_id(designated):
        raise RuntimeError("管理員預先指定 LINE User ID 格式錯誤")
    member = get("member:" + designated, {})
    if not _eligible_bootstrap_member(member):
        raise RuntimeError("指定帳號尚未完成 LINE 註冊及平台密碼設定")
    with Session.begin() as session:
        row = session.get(AdminBootstrap, 1)
        if row is not None:
            if (not hmac.compare_digest(row.designated_user, designated) or
                not hmac.compare_digest(row.designated_line_user_id, designated)):
                raise RuntimeError("最高管理員已預先指定其他帳號；禁止覆寫")
            return "already_designated"
        session.add(AdminBootstrap(id=1, designated_user=designated,
                                   designated_line_user_id=designated,
                                   initialized=False))
        try:
            session.flush()
        except IntegrityError:
            # Concurrent startup: fail closed and let a later startup verify.
            raise RuntimeError("管理員預先指定發生競爭，請重試啟動")
    return "designated"
