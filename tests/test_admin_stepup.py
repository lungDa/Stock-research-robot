"""Step-up OTP authorization: fail-closed, scoped, device-specific, single-use."""
import time
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.api.server import app
from app.api.line_login import digest
from app.api import device_sessions
from app.db import get, put
from app.day_trader import admin_stepup
from app.services.accounts import register, password_hash
from app.day_trader.access_models import AdminBootstrap
from app.db import Session

U = "U" + "e" * 32
V = "U" + "f" * 32

def login(user, token):
    register(user, "test")
    member = get("member:" + user)
    member.update(password_hash=password_hash("12345678"), password_change_required=False,
                  activation_pending=False, password_version="v1")
    put("member:" + user, member)
    sid = digest(token)
    expiry = time.time() + 3600
    device_sessions.register(sid, user, expiry)
    put("auth:session:" + sid, {"user": user, "stage": "active",
        "expires": expiry, "password_version": "v1", "session_id": sid})
    return {"Authorization": "Bearer " + token}

def test_stepup_requires_bootstrap_and_is_scoped_to_device_and_action(monkeypatch):
    sent = []
    monkeypatch.setattr(admin_stepup.line, "push", lambda user, text, key: sent.append((user, text)))
    monkeypatch.setattr(admin_stepup.secrets, "randbelow", lambda n: 123456)
    with TestClient(app) as client:
        a = login(U, "admin-device-a")
        b = login(U, "admin-device-b")
        outsider = login(V, "other-device")
        assert client.post("/admin/stepup/otp", headers=a, json={"scope":"ai_limits"}).status_code == 403
        with Session.begin() as db:
            db.add(AdminBootstrap(id=1, designated_user=U, designated_line_user_id=U, initialized=True))
        assert client.post("/admin/stepup/otp", headers=outsider, json={"scope":"ai_limits"}).status_code == 403
        assert client.post("/admin/stepup/otp", headers=a, json={"scope":"unknown"}).status_code == 400
        assert client.post("/admin/stepup/otp", headers=a, json={"scope":"ai_limits"}).status_code == 200
        assert sent[0][0] == U
        assert client.post("/admin/stepup/verify", headers=b,
                           json={"scope":"ai_limits","code":"123456"}).status_code == 403
        assert client.post("/admin/stepup/verify", headers=a,
                           json={"scope":"role_management","code":"123456"}).status_code == 403
        assert client.post("/admin/stepup/verify", headers=a,
                           json={"scope":"ai_limits","code":"000000"}).status_code == 403
        assert client.post("/admin/stepup/verify", headers=a,
                           json={"scope":"ai_limits","code":"123456"}).json()["authorized"]
        assert client.post("/admin/stepup/verify", headers=a,
                           json={"scope":"ai_limits","code":"123456"}).status_code == 403
        assert client.get("/admin/stepup/status", headers=a).json()["authorized"]
        assert not client.get("/admin/stepup/status", headers=b).json()["authorized"]
        assert admin_stepup.require(_request(a), "ai_limits") == U
        with pytest.raises(HTTPException):
            admin_stepup.require(_request(a), "role_management")
        assert client.post("/auth/logout", headers=a).status_code == 200
        assert client.get("/admin/stepup/status", headers=a).status_code == 401

def _request(headers):
    from starlette.requests import Request
    token = headers["Authorization"]
    return Request({"type":"http", "method":"GET", "path":"/",
                    "headers":[(b"authorization", token.encode())]})
