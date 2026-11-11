"""V2.5 管理員初始化 API 安全回歸測試：未授權拒絕、身分不洩漏、OTP 不可冒領。"""
from fastapi.testclient import TestClient
from app.api.server import app
from app.api.security import current_user

OWNER = "U" + "a" * 32
OTHER = "U" + "b" * 32


def test_bootstrap_endpoints_reject_anonymous():
    with TestClient(app) as client:
        assert client.get("/admin/bootstrap/status").status_code == 401
        assert client.post("/admin/bootstrap/otp").status_code == 401
        assert client.post("/admin/bootstrap/verify", json={"code": "123456"}).status_code == 401


def test_bootstrap_status_does_not_disclose_designated_identity(monkeypatch):
    from app.day_trader import admin_bootstrap
    monkeypatch.setattr(admin_bootstrap, "_record", lambda: {
        "user": OWNER, "line_id": OWNER, "initialized": False,
    })
    app.dependency_overrides[current_user] = lambda: OTHER
    try:
        with TestClient(app) as client:
            response = client.get("/admin/bootstrap/status")
            assert response.status_code == 200
            assert response.json() == {"designated": False, "initialized": False}
    finally:
        app.dependency_overrides.pop(current_user, None)


def test_other_member_cannot_request_admin_otp(monkeypatch):
    from app.day_trader import admin_bootstrap
    monkeypatch.setattr(admin_bootstrap, "_record", lambda: {
        "user": OWNER, "line_id": OWNER, "initialized": False,
    })
    app.dependency_overrides[current_user] = lambda: OTHER
    try:
        with TestClient(app) as client:
            assert client.post("/admin/bootstrap/otp").status_code == 403
    finally:
        app.dependency_overrides.pop(current_user, None)


def test_bootstrap_rejects_malformed_otp():
    app.dependency_overrides[current_user] = lambda: OWNER
    try:
        with TestClient(app) as client:
            for value in ("12345", "1234567", "abcdef", "１２３４５６"):
                assert client.post("/admin/bootstrap/verify", json={"code": value}).status_code == 422
    finally:
        app.dependency_overrides.pop(current_user, None)
