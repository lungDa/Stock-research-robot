"""Sensitive AI-limit writes must enforce real device-bound step-up grants."""
import time
from fastapi.testclient import TestClient
from app.api.server import app
from app.api.line_login import digest
from app.api import device_sessions
from app.db import get, put, Session
from app.services.accounts import register, password_hash
from app.day_trader.access_models import AdminBootstrap, UserAILimit

ADMIN = "U" + "7" * 32
TARGET = "U" + "6" * 32

def session_for(token):
    register(ADMIN, "test")
    member = get("member:" + ADMIN)
    member.update(password_hash=password_hash("12345678"), password_change_required=False,
                  activation_pending=False, password_version="v1")
    put("member:" + ADMIN, member)
    sid = digest(token)
    expiry = time.time() + 3600
    device_sessions.register(sid, ADMIN, expiry)
    put("auth:session:" + sid, {"user": ADMIN, "stage": "active",
        "expires": expiry, "password_version": "v1", "session_id": sid})
    return {"Authorization": "Bearer " + token}, sid

def test_ai_limit_write_requires_scoped_stepup_on_same_device(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "login_channel_id", "configured")
    with TestClient(app) as client:
        with Session.begin() as db:
            db.add(AdminBootstrap(id=1, designated_user=ADMIN,
                                  designated_line_user_id=ADMIN, initialized=True))
        a, sid_a = session_for("ai-limit-admin-a")
        b, sid_b = session_for("ai-limit-admin-b")
        url = "/admin/ai-limits/" + TARGET
        body = {"normal_daily_limit": 25, "emergency_daily_limit": 3}
        assert client.put(url, headers=a, json=body).status_code == 403
        put("admin:stepup:" + sid_a, {"user": ADMIN, "scope": "role_management",
            "grant_expires": time.time() + 600})
        assert client.put(url, headers=a, json=body).status_code == 403
        put("admin:stepup:" + sid_a, {"user": ADMIN, "scope": "ai_limits",
            "grant_expires": time.time() + 600})
        assert client.put(url, headers=b, json=body).status_code == 403
        response = client.put(url, headers=a, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["normal_daily_limit"] == 25
        with Session() as db:
            row = db.get(UserAILimit, TARGET)
            assert row.normal_daily_limit == 25 and row.emergency_daily_limit == 3
        assert client.put(url, headers=a, json={"normal_daily_limit":-1,
            "emergency_daily_limit":0}).status_code == 422
        device_sessions.revoke(sid_a, ADMIN)
        assert client.put(url, headers=a, json=body).status_code in (401,403)

def test_legacy_admin_does_not_bypass_stepup(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "login_channel_id", "configured")
    monkeypatch.setenv("ADMIN_LINE_USER_IDS", "U" + "5" * 32)
    with TestClient(app) as client:
        result = client.put("/admin/ai-limits/" + TARGET,
                            headers={"Authorization":"Bearer fake"},
                            json={"normal_daily_limit":10,"emergency_daily_limit":0})
        assert result.status_code in (401,403)
