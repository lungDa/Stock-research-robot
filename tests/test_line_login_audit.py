"""Regression checks for shared-proxy LINE starts and admin notification audit."""
from fastapi.testclient import TestClient
from app.api.server import app
from app.api import line_login
from app.config import settings

def test_shared_proxy_allows_more_than_ten_distinct_logins(monkeypatch):
    for key,value in dict(login_channel_id="12345",login_channel_secret="test",
        login_callback="https://testserver/auth/line/callback",
        public_app_url="https://frontend.example",api_public_url="https://testserver").items():
        monkeypatch.setattr(settings,key,value)
    with TestClient(app,base_url="https://testserver") as client:
        for _ in range(11):
            response=client.post("/auth/line/start",json={})
            assert response.status_code==200, response.text
            assert "/auth/line/authorize?" in response.json()["authorize_url"]

def test_admin_alert_audits_success_and_failure(monkeypatch):
    from app.day_trader import login_alerts
    from app.day_trader import admin_bootstrap
    from app.channels import line
    from app.db import get
    from hashlib import sha256
    monkeypatch.setattr(admin_bootstrap,"admin_identity_matches",lambda u:True)
    monkeypatch.setattr(line,"push",lambda *args:None)
    sid="audit-success-device"
    assert login_alerts.notify_admin_login("U"+"a"*32,sid)
    assert get("auth:admin-login-alert:"+sha256(sid.encode()).hexdigest())["status"]=="sent"
    def failed(*args):
        raise RuntimeError("LINE unavailable")
    monkeypatch.setattr(line,"push",failed)
    sid="audit-failed-device"
    assert not login_alerts.notify_admin_login("U"+"a"*32,sid)
    assert get("auth:admin-login-alert:"+sha256(sid.encode()).hexdigest())["status"]=="failed"
