"""LINE security alerts must never disclose tokens or interrupt login on failure."""
from app.day_trader import login_alerts

ADMIN = "U" + "a" * 32

def test_admin_login_alert_contains_no_session_secret(monkeypatch):
    sent = []
    monkeypatch.setattr(login_alerts, "notify_admin_login", login_alerts.notify_admin_login)
    monkeypatch.setattr("app.day_trader.admin_bootstrap.admin_identity_matches",
                        lambda user: user == ADMIN)
    monkeypatch.setattr("app.channels.line.push",
                        lambda user, message, key: sent.append((user, message)))
    secret = "private-token-should-not-appear"
    assert login_alerts.notify_admin_login(ADMIN, secret)
    assert sent[0][0] == ADMIN
    assert "新的管理員登入工作階段" in sent[0][1]
    assert secret not in sent[0][1]

def test_non_admin_does_not_get_admin_alert(monkeypatch):
    monkeypatch.setattr("app.day_trader.admin_bootstrap.admin_identity_matches",
                        lambda user: False)
    monkeypatch.setattr("app.channels.line.push",
                        lambda *args: (_ for _ in ()).throw(AssertionError("must not send")))
    assert login_alerts.notify_admin_login(ADMIN, "session") is False

def test_line_failure_does_not_block_login(monkeypatch):
    monkeypatch.setattr("app.day_trader.admin_bootstrap.admin_identity_matches",
                        lambda user: True)
    monkeypatch.setattr("app.channels.line.push",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("network unavailable")))
    assert login_alerts.notify_admin_login(ADMIN, "session") is False
