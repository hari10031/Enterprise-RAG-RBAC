import threading
import time
from collections import deque
from dataclasses import dataclass
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException

from eka.core import acl
from eka.core.config import settings
from eka.core.db import pool
from eka.core.security import token_hash

COOKIE = "eka_session"


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    display_name: str
    group_ids: list[UUID]  # resolved once per request and passed explicitly into retrieval
    is_admin: bool


def current_user(eka_session: str | None = Cookie(default=None)) -> User:
    if not eka_session:
        raise HTTPException(401, "not signed in")
    with pool().connection() as conn:
        row = conn.execute(
            """SELECT u.id, u.email, u.display_name FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.id = %s AND s.expires_at > now() AND u.is_active""",
            (token_hash(eka_session),),
        ).fetchone()
        if row is None:
            raise HTTPException(401, "session expired")
        groups = acl.user_group_ids(conn, row["id"])
        is_admin = acl.admins_group_id(conn) in groups
    return User(row["id"], row["email"], row["display_name"], groups, is_admin)


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "admins only")
    return user


class RateLimiter:
    """Sliding one-minute window per user, in process memory (single API process, D1)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[UUID, deque[float]] = {}
        self.lock = threading.Lock()

    def check(self, user_id: UUID) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits.setdefault(user_id, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                raise HTTPException(429, "too many questions; wait a minute")
            q.append(now)


query_limiter = RateLimiter(settings.queries_per_minute)
