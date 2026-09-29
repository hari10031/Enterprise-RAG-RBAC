from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from eka.core import acl
from eka.core.config import settings
from eka.core.db import pool
from eka.core.security import (
    DUMMY_HASH,
    MIN_PASSWORD_LENGTH,
    hash_password,
    new_session_token,
    token_hash,
    verify_password,
)
from eka.web.deps import COOKIE, User, current_user

router = APIRouter(prefix="/auth", tags=["auth"])
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)


@router.post("/login")
def login(body: LoginIn, response: Response) -> dict[str, str]:
    denied = HTTPException(401, "wrong email or password, or account locked")
    with pool().connection() as conn:
        user = conn.execute(
            "SELECT id, password_hash, failed_logins, locked_until, is_active FROM users "
            "WHERE lower(email) = lower(%s)",
            (body.email,),
        ).fetchone()
        if user is None or not user["is_active"]:
            verify_password(DUMMY_HASH, body.password)
            raise denied
        now = datetime.now(UTC)
        if user["locked_until"] and user["locked_until"] > now:
            raise denied
        if not verify_password(user["password_hash"], body.password):
            failed = user["failed_logins"] + 1
            locked = now + LOCKOUT if failed >= MAX_FAILED_LOGINS else None
            conn.execute(
                "UPDATE users SET failed_logins = %s, locked_until = %s WHERE id = %s",
                (0 if locked else failed, locked, user["id"]),
            )
            acl.audit(conn, user["id"], "login_failed", {"locked": locked is not None})
            raise denied
        token, sid = new_session_token()
        with conn.transaction():
            conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = %s", (user["id"],))
            conn.execute(
                "INSERT INTO sessions (id, user_id, expires_at) VALUES (%s, %s, %s)",
                (sid, user["id"], now + timedelta(hours=settings.session_hours)),
            )
            conn.execute("DELETE FROM sessions WHERE expires_at < now()")
        acl.audit(conn, user["id"], "login", {})
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api",
    )
    return {"status": "ok"}


@router.post("/logout")
def logout(response: Response, eka_session: str | None = Cookie(default=None)) -> dict[str, str]:
    if eka_session:
        with pool().connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (token_hash(eka_session),))
    response.delete_cookie(COOKIE, path="/api")
    return {"status": "ok"}


@router.post("/password")
def change_password(body: PasswordIn, user: User = Depends(current_user)) -> dict[str, str]:
    with pool().connection() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user.id,)).fetchone()
        if row is None or not verify_password(row["password_hash"], body.current_password):
            raise HTTPException(400, "current password is wrong")
        conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(body.new_password), user.id))
    return {"status": "ok"}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict[str, object]:
    with pool().connection() as conn:
        groups = conn.execute(
            "SELECT id, name FROM groups WHERE id = ANY(%s) ORDER BY name", (user.group_ids,)
        ).fetchall()
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "groups": groups,  # the user's own groups, shown as "answering from" in the chat
        "is_admin": user.is_admin,
    }
