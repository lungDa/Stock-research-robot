"""Risk-based LINE OTP gate for suspicious administrator password verification.

A failed password on the current session triggers step-up after the correct password.
Existing account-wide rate limiting remains in force; no other session is blocked.
"""
import hashlib
import hmac
import re
import secrets
import time
from fastapi import HTTPException
from app.db import acquire_lease, release_lease, get, put
from app.channels import line
from app.day_trader.admin_bootstrap import admin_identity_matches

TTL = 300
MAX_ATTEMPTS = 5
LOCK_SECONDS = 600

def _key(sid):
    return "auth:risk:" + sid

def note_password_failure(sid):
    key = _key(sid)
    lease = acquire_lease(key + ":lock", seconds=20)
    if not lease:
        return
    try:
        state = get(key, {})
        state["password_failures"] = min(100, state.get("password_failures", 0) + 1)
        put(key, state)
    finally:
        release_lease(key + ":lock", lease)

def challenge_required(user, sid):
    return admin_identity_matches(user) and get(_key(sid), {}).get("password_failures", 0) > 0

def issue(user, sid):
    if not admin_identity_matches(user):
        raise HTTPException(403, "無權使用管理員安全驗證")
    key = _key(sid)
    lease = acquire_lease(key + ":lock", seconds=20)
    if not lease:
        raise HTTPException(429, "驗證程序忙碌")
    try:
        state = get(key, {})
        now = time.time()
        if state.get("locked_until", 0) > now:
            raise HTTPException(429, "此工作階段暫時無法驗證")
        if state.get("expires", 0) > now:
            raise HTTPException(429, "驗證碼已發送，請稍後重試")
        code = f"{secrets.randbelow(1000000):06d}"
        salt = secrets.token_hex(16)
        state.update(salt=salt, code_hash=hashlib.sha256((salt + ":" + code).encode()).hexdigest(),
                     expires=now + TTL, attempts=0)
        put(key, state)
        line.push(user, "股海燈塔異常登入驗證碼：" + code + "（5分鐘有效）",
                  secrets.token_hex(16))
        return {"sent": True, "expires_in": TTL}
    finally:
        release_lease(key + ":lock", lease)

def verify(user, sid, code):
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise HTTPException(400, "驗證碼格式錯誤")
    key = _key(sid)
    lease = acquire_lease(key + ":lock", seconds=20)
    if not lease:
        raise HTTPException(429, "驗證程序忙碌")
    try:
        state = get(key, {})
        now = time.time()
        if state.get("locked_until", 0) > now:
            raise HTTPException(429, "此工作階段暫時無法驗證")
        if state.get("expires", 0) <= now or state.get("attempts", MAX_ATTEMPTS) >= MAX_ATTEMPTS:
            raise HTTPException(403, "驗證碼無效或已過期")
        state["attempts"] += 1
        actual = hashlib.sha256((state.get("salt", "") + ":" + code).encode()).hexdigest()
        if not hmac.compare_digest(actual, state.get("code_hash", "")):
            if state["attempts"] >= MAX_ATTEMPTS:
                state["locked_until"] = now + LOCK_SECONDS
            put(key, state)
            raise HTTPException(403, "驗證碼無效或已過期")
        put(key, {"password_failures": 0, "expires": 0, "attempts": MAX_ATTEMPTS})
        return True
    finally:
        release_lease(key + ":lock", lease)
