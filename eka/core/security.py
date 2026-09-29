import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_ph = PasswordHasher()  # argon2id with library defaults
# Verified against when the email is unknown, so response time does not reveal which emails exist.
DUMMY_HASH = _ph.hash("dummy-password-for-timing")
MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session_token() -> tuple[str, str]:
    """Returns (token for the cookie, hash for the sessions table)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)
