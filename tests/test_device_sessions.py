"""Device session isolation and remote revocation, using the existing authenticated session contract."""
import time
from fastapi.testclient import TestClient
from app.api.server import app
from app.api.line_login import digest
from app.api import device_sessions
from app.db import get, put
from app.services.accounts import register, password_hash

USER = "U" + "c" * 32
OTHER = "U" + "d" * 32

def active(user, token):
    register(user, "test")
    member = get("member:" + user)
    member.update(password_hash=password_hash("12345678"), password_change_required=False,
                  activation_pending=False, password_version="version")
    put("member:" + user, member)
    sid = digest(token)
    expiry = time.time() + 3600
    device_sessions.register(sid, user, expiry)
    put("auth:session:" + sid, {"user": user, "stage": "active", "expires": expiry,
                                 "password_version": "version", "session_id": sid})
    return {"Authorization": "Bearer " + token}

def test_revoke_one_device_keeps_other_device_active(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "login_channel_id", "configured")
    with TestClient(app) as client:
        a = active(USER, "device-token-a")
        b = active(USER, "device-token-b")
        other = active(OTHER, "device-token-other")
        response = client.get("/auth/devices", headers=a)
        assert response.status_code == 200
        assert len(response.json()["devices"]) == 2
        assert client.post("/auth/devices/" + digest("device-token-b") + "/revoke", headers=a).json() == {"revoked": True}
        assert client.get("/watchlist", headers=a).status_code == 200
        assert client.get("/watchlist", headers=b).status_code == 403
        assert client.get("/watchlist", headers=other).status_code == 200
        assert client.post("/auth/devices/" + digest("device-token-other") + "/revoke", headers=a).json() == {"revoked": False}

def test_revoke_other_sessions_and_logout(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "login_channel_id", "configured")
    with TestClient(app) as client:
        a = active(USER, "session-a")
        b = active(USER, "session-b")
        assert client.post("/auth/devices/revoke-others", headers=a).json() == {"revoked": 1}
        assert client.get("/watchlist", headers=b).status_code == 403
        assert client.get("/watchlist", headers=a).status_code == 200
        assert client.post("/auth/logout", headers=a).status_code == 200
        assert client.get("/watchlist", headers=a).status_code == 403
