from app.day_trader.admin_bootstrap import _hash_otp, _valid_line_id, admin_identity_matches

def test_line_id_format():
    assert _valid_line_id("U" + "a"*32)
    assert not _valid_line_id("U" + "z"*32)
    assert not _valid_line_id("U" + "a"*31)

def test_otp_digest_deterministic_and_salted():
    assert _hash_otp("123456","salt") == _hash_otp("123456","salt")
    assert _hash_otp("123456","salt") != _hash_otp("123456","other")

def test_legacy_completed_member_can_bootstrap():
    from app.day_trader.admin_bootstrap import _eligible_bootstrap_member
    legacy = {
        "active": True,
        "password_hash": "scrypt$" + "a" * 32 + "$" + "b" * 128,
        "password_change_required": False,
        "password_version": "rotated-version",
    }
    assert _eligible_bootstrap_member(legacy)
    assert _eligible_bootstrap_member({**legacy, "activation_pending": False})
    assert not _eligible_bootstrap_member({**legacy, "activation_pending": True})
    assert not _eligible_bootstrap_member({**legacy, "activation_pending": None})
    assert not _eligible_bootstrap_member({**legacy, "active": False})
    assert not _eligible_bootstrap_member({**legacy, "password_change_required": True})
    assert not _eligible_bootstrap_member({**legacy, "password_hash": ""})
    assert not _eligible_bootstrap_member({**legacy, "password_version": ""})


def test_super_admin_inherits_legacy_admin_access(monkeypatch):
    from app.api import security
    monkeypatch.setenv("ADMIN_LINE_USER_IDS", "Ulegacy")
    monkeypatch.setattr("app.day_trader.admin_bootstrap.admin_identity_matches",
                        lambda user: user == "Usuper")
    assert security.is_admin("Ulegacy")
    assert security.is_admin("Usuper")
    assert not security.is_admin("Uother")
