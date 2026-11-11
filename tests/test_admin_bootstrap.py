from app.day_trader.admin_bootstrap import _hash_otp, _valid_line_id, admin_identity_matches

def test_line_id_format():
    assert _valid_line_id("U" + "a"*32)
    assert not _valid_line_id("U" + "z"*32)
    assert not _valid_line_id("U" + "a"*31)

def test_otp_digest_deterministic_and_salted():
    assert _hash_otp("123456","salt") == _hash_otp("123456","salt")
    assert _hash_otp("123456","salt") != _hash_otp("123456","other")
