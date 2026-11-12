"""Password rotation revokes other devices and invalidates old step-up grants."""
import time
from fastapi.testclient import TestClient
from app.api.server import app
from app.api.line_login import digest
from app.api import device_sessions
from app.db import get, put
from app.services.accounts import register, password_hash

USER = "U" + "9" * 32
OTHER = "U" + "8" * 32

def login(user, token):
    register(user, "test")
    member = get("member:" + user)
    member.update(password_hash=password_hash("12345678"),
                  password_change_required=False, activation_pending=False,
                  password_version="before")
    put("member:" + user, member)
    sid = digest(token)
    expiry = time.time() + 3600
    device_sessions.register(sid, user, expiry)
    put("auth:session:" + sid, {"user": user, "stage": "active",
        "expires": expiry, "password_version": "before", "session_id": sid})
    return {"Authorization": "Bearer " + token}

def test_password_change_revokes_all_other_devices_and_stepup(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "login_channel_id", "configured")
    with TestClient(app) as client:
        current = login(USER, "rotation-current")
        other = login(USER, "rotation-other")
        unrelated = login(OTHER, "rotation-unrelated")
        current_sid = digest("rotation-current")
        other_sid = digest("rotation-other")
        put("admin:stepup:" + current_sid,
            {"user": USER, "scope": "ai_limits", "grant_expires": time.time() + 600})
        put("admin:stepup:" + other_sid,
            {"user": USER, "scope": "ai_limits", "grant_expires": time.time() + 600})
        response = client.post("/auth/password/change", headers=current,
            json={"current_password": "12345678", "new_password": "87654321"})
        assert response.status_code == 200, response.text
        assert device_sessions.permitted(current_sid)
        assert not device_sessions.permitted(other_sid)
        assert client.get("/watchlist", headers=current).status_code == 200
        assert client.get("/watchlist", headers=other).status_code in (401, 403)
        assert client.get("/watchlist", headers=unrelated).status_code == 200
        assert get("admin:stepup:" + current_sid, {}).get("grant_expires", 0) == 0
        # A stale grant record on another device cannot be used: its session is revoked.
        assert client.get("/auth/me", headers=other).status_code == 401

def test_rejected_password_change_does_not_revoke_other_device(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "login_channel_id", "configured")
    with TestClient(app) as client:
        current = login(USER, "rotation-failed-current")
        other = login(USER, "rotation-failed-other")
        response = client.post("/auth/password/change", headers=current,
            json={"current_password": "00000000", "new_password": "87654321"})
        assert response.status_code == 403
        assert device_sessions.permitted(digest("rotation-failed-other"))
        assert client.get("/watchlist", headers=other).status_code == 200

def test_active_password_rotation_preserves_absolute_expiry(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "login_channel_id", "configured")
    with TestClient(app) as client:
        headers = login(USER, "rotation-fixed-expiry")
        sid = digest("rotation-fixed-expiry")
        before = get("auth:session:" + sid)["expires"]
        response = client.post("/auth/password/change", headers=headers,
            json={"current_password": "12345678", "new_password": "87654321"})
        assert response.status_code == 200, response.text
        assert get("auth:session:" + sid)["expires"] == before
        from app.db import Session
        with Session() as db:
            row = db.get(device_sessions.LoginDevice, sid)
            assert row.expires_at == before
        assert client.get("/auth/me", headers=headers).status_code == 200
