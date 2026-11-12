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


def test_initialization_push_uses_uuid_retry_key(monkeypatch):
    import uuid
    from app.day_trader import admin_bootstrap as bootstrap
    from app import db
    user = 'U' + 'a' * 32
    stored = {}
    monkeypatch.setattr(bootstrap, '_record', lambda: {'user': user, 'line_id': user, 'initialized': False})
    monkeypatch.setattr(db, 'acquire_lease', lambda *args, **kwargs: 'lease')
    monkeypatch.setattr(db, 'release_lease', lambda *args, **kwargs: None)
    monkeypatch.setattr(db, 'get', lambda key, default=None: stored.get(key, default))
    monkeypatch.setattr(db, 'put', lambda key, value: stored.__setitem__(key, value))
    seen = []
    monkeypatch.setattr(bootstrap.line, 'push', lambda recipient, message, key: seen.append((recipient, message, key)))
    assert bootstrap.issue_initialization_otp(user)['sent']
    assert seen[0][0] == user
    assert str(uuid.UUID(seen[0][2])) == seen[0][2]
    assert 'digest' in stored['admin:bootstrap:otp']
