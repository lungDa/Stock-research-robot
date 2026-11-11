"""Single-superadministrator policy and protected security actions."""
import time
from fastapi.testclient import TestClient
from app.api.server import app
from app.api.line_login import digest
from app.api import device_sessions
from app.db import get, put, Session
from app.services.accounts import register, password_hash
from app.day_trader.access_models import AdminBootstrap

ADMIN = "U" + "a" * 32

def auth(token):
    register(ADMIN, "test")
    member = get("member:" + ADMIN)
    member.update(password_hash=password_hash("12345678"), password_change_required=False,
                  activation_pending=False, password_version="v1")
    put("member:" + ADMIN, member)
    sid = digest(token)
    expires = time.time() + 3600
    device_sessions.register(sid, ADMIN, expires)
    put("auth:session:" + sid, {"user": ADMIN, "stage": "active",
        "expires": expires, "password_version": "v1", "session_id": sid})
    return {"Authorization": "Bearer " + token}, sid

def test_security_action_requires_matching_stepup_and_single_admin_is_immutable(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "login_channel_id", "configured")
    with TestClient(app) as client:
        with Session.begin() as db:
            db.add(AdminBootstrap(id=1, designated_user=ADMIN,
                                  designated_line_user_id=ADMIN, initialized=True))
        current, sid = auth("single-admin-current")
        other, other_sid = auth("single-admin-other")
        assert client.get("/admin/role-policy", headers=current).json()["mode"] == "single_superadmin"
        assert client.post("/admin/security/revoke-other-devices", headers=current).status_code == 403
        assert device_sessions.permitted(other_sid)
        put("admin:stepup:" + sid, {"user": ADMIN, "scope": "ai_limits",
            "grant_expires": time.time() + 600})
        assert client.post("/admin/security/revoke-other-devices", headers=current).status_code == 403
        put("admin:stepup:" + sid, {"user": ADMIN, "scope": "security_settings",
            "grant_expires": time.time() + 600})
        response = client.post("/admin/security/revoke-other-devices", headers=current)
        assert response.status_code == 200, response.text
        assert device_sessions.permitted(sid)
        assert not device_sessions.permitted(other_sid)
        assert client.post("/admin/security/revoke-other-devices", headers=other).status_code in (401,403)
        assert client.put("/admin/roles/" + ("U" + "b"*32), headers=current,
                          json={"role":"admin"}).status_code == 403
        put("admin:stepup:" + sid, {"user": ADMIN, "scope": "role_management",
            "grant_expires": time.time() + 600})
        assert client.put("/admin/roles/" + ("U" + "b"*32), headers=current,
                          json={"role":"admin"}).status_code == 403
