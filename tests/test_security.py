from eka.core.security import hash_password, new_session_token, token_hash, verify_password


def test_password_hash_is_argon2id() -> None:
    h = hash_password("correct horse battery")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery")
    assert not verify_password(h, "wrong")
    assert not verify_password("not-a-hash", "x")


def test_session_token_stored_as_hash() -> None:
    token, sid = new_session_token()
    assert sid == token_hash(token) and token not in sid and len(sid) == 64
