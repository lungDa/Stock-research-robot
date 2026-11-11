"""Risk OTP challenge: per-session isolation, 5 attempts, expiry, single-use."""
import time
import pytest
from fastapi import HTTPException
from app.day_trader import login_risk

ADMIN = "U" + "a" * 32

def test_risk_gate_is_session_scoped(monkeypatch):
    monkeypatch.setattr(login_risk, "admin_identity_matches", lambda user: user == ADMIN)
    sid = "risk-test-device-a"
    other = "risk-test-device-b"
    login_risk.note_password_failure(sid)
    assert login_risk.challenge_required(ADMIN, sid)
    assert not login_risk.challenge_required(ADMIN, other)
    assert not login_risk.challenge_required("U" + "b" * 32, sid)

def test_risk_otp_single_use_and_lockout(monkeypatch):
    monkeypatch.setattr(login_risk, "admin_identity_matches", lambda user: True)
    monkeypatch.setattr(login_risk.secrets, "randbelow", lambda n: 123456)
    sent = []
    monkeypatch.setattr(login_risk.line, "push", lambda *args: sent.append(args))
    sid = "risk-test-otp-single"
    login_risk.note_password_failure(sid)
    assert login_risk.issue(ADMIN, sid)["sent"]
    assert sent[0][0] == ADMIN
    for _ in range(4):
        with pytest.raises(HTTPException) as exc:
            login_risk.verify(ADMIN, sid, "000000")
        assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        login_risk.verify(ADMIN, sid, "000000")
    with pytest.raises(HTTPException) as exc:
        login_risk.verify(ADMIN, sid, "123456")
    assert exc.value.status_code == 429

def test_risk_otp_success_clears_risk(monkeypatch):
    monkeypatch.setattr(login_risk, "admin_identity_matches", lambda user: True)
    monkeypatch.setattr(login_risk.secrets, "randbelow", lambda n: 123456)
    monkeypatch.setattr(login_risk.line, "push", lambda *args: None)
    sid = "risk-test-otp-success"
    login_risk.note_password_failure(sid)
    login_risk.issue(ADMIN, sid)
    assert login_risk.verify(ADMIN, sid, "123456")
    assert not login_risk.challenge_required(ADMIN, sid)
    with pytest.raises(HTTPException):
        login_risk.verify(ADMIN, sid, "123456")
