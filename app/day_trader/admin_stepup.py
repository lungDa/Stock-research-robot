"""Device-scoped step-up authorization for sensitive administrator operations.

Never grants initial administrator identity; bootstrap must already be complete.
"""
import hashlib
import hmac
import re
import secrets
import time
from fastapi import HTTPException, Request
from app.api.line_login import digest, session_info
from app.api.device_sessions import permitted
from app.day_trader.admin_bootstrap import admin_identity_matches
from app.db import acquire_lease, release_lease, get, put
from app.channels import line

OTP_TTL = 300
GRANT_TTL = 600
MAX_ATTEMPTS = 5
SCOPES = frozenset({"ai_limits", "role_management", "security_settings"})
KEY_PREFIX = "admin:stepup:"

def _identity(request):
    _, session, member = session_info(request)
    if session.get("stage") != "active" or member.get("password_change_required", True):
        raise HTTPException(403, "請先完成 LINE 與平台密碼驗證")
    user = session["user"]
    if not admin_identity_matches(user):
        raise HTTPException(403, "需要已初始化的最高管理員身分")
    token = request.headers.get("authorization", "")
    if not token.startswith("Bearer "):
        raise HTTPException(401, "登入憑證無效")
    sid = digest(token.removeprefix("Bearer "))
    if session.get("session_id") != sid or not permitted(sid):
        raise HTTPException(403, "裝置工作階段無效")
    return user, sid, session

def _key(sid):
    return KEY_PREFIX + sid

def issue(request, scope):
    if scope not in SCOPES:
        raise HTTPException(400, "不支援的授權類別")
    user, sid, _ = _identity(request)
    key = _key(sid)
    lease = acquire_lease(key + ":lock", seconds=20)
    if not lease:
        raise HTTPException(429, "驗證程序忙碌")
    try:
        state = get(key, {})
        if state.get("challenge_expires", 0) > time.time():
            raise HTTPException(429, "驗證碼已發送，請稍後重試")
        otp = f"{secrets.randbelow(1000000):06d}"
        salt = secrets.token_hex(16)
        put(key, {"scope": scope, "user": user, "salt": salt,
                  "digest": hashlib.sha256((salt + ":" + otp).encode()).hexdigest(),
                  "challenge_expires": time.time() + OTP_TTL, "attempts": 0,
                  "grant_expires": 0})
        # Recipient is derived exclusively from authenticated admin identity.
        line.push(user, "股海燈塔重要操作驗證碼：" + otp +
                  "（5分鐘有效，請勿轉傳）", secrets.token_hex(16))
    finally:
        release_lease(key + ":lock", lease)
    return {"sent": True, "expires_in": OTP_TTL}

def verify(request, scope, code):
    if scope not in SCOPES or not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise HTTPException(400, "驗證資料格式錯誤")
    user, sid, session = _identity(request)
    key = _key(sid)
    lease = acquire_lease(key + ":lock", seconds=20)
    if not lease:
        raise HTTPException(429, "驗證程序忙碌")
    try:
        state = get(key, {})
        now = time.time()
        if (state.get("user") != user or state.get("scope") != scope
                or state.get("challenge_expires", 0) <= now
                or state.get("attempts", MAX_ATTEMPTS) >= MAX_ATTEMPTS):
            raise HTTPException(403, "驗證碼無效或已過期")
        state["attempts"] += 1
        expected = hashlib.sha256((state.get("salt", "") + ":" + code).encode()).hexdigest()
        if not hmac.compare_digest(state.get("digest", ""), expected):
            put(key, state)
            raise HTTPException(403, "驗證碼無效或已過期")
        expiry = min(now + GRANT_TTL, session["expires"])
        put(key, {"user": user, "scope": scope, "grant_expires": expiry,
                  "challenge_expires": 0, "attempts": MAX_ATTEMPTS})
        return {"authorized": True, "expires_in": max(0, int(expiry - now))}
    finally:
        release_lease(key + ":lock", lease)

def require(request, scope):
    user, sid, session = _identity(request)
    state = get(_key(sid), {})
    if (scope not in SCOPES or state.get("user") != user or state.get("scope") != scope
            or state.get("grant_expires", 0) <= time.time()
            or state.get("grant_expires", 0) > session["expires"]):
        raise HTTPException(403, "重要操作需重新進行 LINE OTP 驗證")
    return user
