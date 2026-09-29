"""Documents, users, groups, folder mappings, analytics and health."""

import hashlib
import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from eka.core import acl, jobs
from eka.core.config import settings
from eka.core.db import pool
from eka.core.security import MIN_PASSWORD_LENGTH, hash_password
from eka.generation import llm
from eka.ingestion.parsers import UnsupportedFile, sniff_mime
from eka.ingestion.store import save_bytes
from eka.web.deps import User, current_user, require_admin

router = APIRouter(tags=["admin"])


class UserIn(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)
    group_ids: list[UUID] = []


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class MemberIn(BaseModel):
    user_id: UUID


class FolderIn(BaseModel):
    path: str = Field(min_length=1)
    group_ids: list[UUID] = []


class AclIn(BaseModel):
    group_ids: list[UUID]


# --- documents ---------------------------------------------------------------------------------------------


@router.get("/documents")
def list_documents(user: User = Depends(current_user)) -> list[dict[str, Any]]:
    """Admins see every document; everyone else sees what their groups allow."""
    with pool().connection() as conn:
        return conn.execute(
            """SELECT id, source, folder_id, path, title, mime_type, size_bytes, status, indexed_at, acl_groups
               FROM documents WHERE %(admin)s OR acl_groups && %(g)s::uuid[] ORDER BY title LIMIT 5000""",
            {"admin": user.is_admin, "g": user.group_ids},
        ).fetchall()


@router.post("/documents", status_code=201)
def upload_document(
    file: UploadFile = File(...), group_ids: list[UUID] = Form(default=[]), user: User = Depends(current_user)
) -> dict[str, Any]:
    if not user.is_admin and not set(group_ids) <= set(user.group_ids):
        raise HTTPException(403, "you can only share with groups you belong to")
    data = file.file.read(settings.upload_max_bytes + 1)
    if len(data) > settings.upload_max_bytes:
        raise HTTPException(413, "file is larger than 50 MB")
    name = os.path.basename(file.filename or "upload")
    try:
        mime = sniff_mime(name, data[:8])
    except UnsupportedFile as e:
        raise HTTPException(415, str(e)) from e
    content_hash = hashlib.sha256(data).hexdigest()
    with pool().connection() as conn:
        doc_id = conn.execute(
            """INSERT INTO documents (source, title, mime_type, size_bytes, content_hash, acl_groups)
               VALUES ('upload', %s, %s, %s, %s, %s) RETURNING id""",
            (name, mime, len(data), content_hash, acl.effective_acl(conn, group_ids)),
        ).fetchone()["id"]  # type: ignore[index]
        save_bytes(data, "upload", doc_id, content_hash)
        jobs.enqueue(conn, "ingest", {"document_id": str(doc_id)})
        acl.audit(conn, user.id, "upload", {"document_id": doc_id, "groups": group_ids})
    return {"id": doc_id, "status": "queued"}


@router.post("/documents/{document_id}/reindex")
def reindex(document_id: UUID, admin: User = Depends(require_admin)) -> dict[str, str]:
    with pool().connection() as conn:
        if not conn.execute(
            "UPDATE documents SET status = 'queued' WHERE id = %s RETURNING id", (document_id,)
        ).fetchone():
            raise HTTPException(404, "document not found")
        jobs.enqueue(conn, "ingest", {"document_id": str(document_id)})
    return {"status": "queued"}


@router.put("/documents/{document_id}/acl")
def set_document_acl(document_id: UUID, body: AclIn, admin: User = Depends(require_admin)) -> dict[str, str]:
    with pool().connection() as conn:
        doc = conn.execute("SELECT source FROM documents WHERE id = %s", (document_id,)).fetchone()
        if doc is None:
            raise HTTPException(404, "document not found")
        if doc["source"] == "folder":
            raise HTTPException(409, "folder documents inherit the folder mapping; change the folder instead")
        acl.set_document_acl(conn, document_id, body.group_ids)
        acl.audit(conn, admin.id, "acl_change", {"document_id": document_id, "groups": body.group_ids})
    return {"status": "ok"}


# --- users and groups --------------------------------------------------------------------------------------


@router.get("/users")
def list_users(admin: User = Depends(require_admin)) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        return conn.execute(
            """SELECT u.id, u.email, u.display_name, u.is_active, u.locked_until,
                      coalesce(array_agg(ug.group_id) FILTER (WHERE ug.group_id IS NOT NULL), '{}') AS group_ids
               FROM users u LEFT JOIN user_groups ug ON ug.user_id = u.id
               GROUP BY u.id ORDER BY u.email"""
        ).fetchall()


@router.post("/users", status_code=201)
def create_user(body: UserIn, admin: User = Depends(require_admin)) -> dict[str, Any]:
    with pool().connection() as conn, conn.transaction():
        if conn.execute("SELECT 1 FROM users WHERE lower(email) = lower(%s)", (body.email,)).fetchone():
            raise HTTPException(409, "email already exists")
        user_id = conn.execute(
            "INSERT INTO users (email, display_name, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (body.email, body.display_name, hash_password(body.password)),
        ).fetchone()["id"]  # type: ignore[index]
        for g in body.group_ids:
            conn.execute("INSERT INTO user_groups (user_id, group_id) VALUES (%s, %s)", (user_id, g))
        acl.audit(conn, admin.id, "acl_change", {"user_id": user_id, "added_groups": body.group_ids})
    return {"id": user_id}


@router.delete("/users/{user_id}")
def deactivate_user(user_id: UUID, admin: User = Depends(require_admin)) -> dict[str, str]:
    """Deactivates rather than deletes, so conversations and the audit trail stay intact."""
    if user_id == admin.id:
        raise HTTPException(400, "you cannot deactivate yourself")
    with pool().connection() as conn, conn.transaction():
        conn.execute("UPDATE users SET is_active = false WHERE id = %s", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        acl.audit(conn, admin.id, "acl_change", {"deactivated_user": user_id})
    return {"status": "ok"}


@router.get("/groups")
def list_groups(user: User = Depends(require_admin)) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        return conn.execute("SELECT id, name, description FROM groups ORDER BY name").fetchall()


@router.post("/groups", status_code=201)
def create_group(body: GroupIn, admin: User = Depends(require_admin)) -> dict[str, Any]:
    with pool().connection() as conn:
        row = conn.execute(
            "INSERT INTO groups (name, description) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING RETURNING id",
            (body.name, body.description),
        ).fetchone()
        if row is None:
            raise HTTPException(409, "group already exists")
    return {"id": row["id"]}


@router.delete("/groups/{group_id}")
def delete_group(group_id: UUID, admin: User = Depends(require_admin)) -> dict[str, str]:
    with pool().connection() as conn:
        if group_id == acl.admins_group_id(conn):
            raise HTTPException(400, "the admins group cannot be deleted")
        conn.execute("DELETE FROM groups WHERE id = %s", (group_id,))
        acl.audit(conn, admin.id, "acl_change", {"deleted_group": group_id})
    return {"status": "ok"}


@router.get("/groups/{group_id}/members")
def list_members(group_id: UUID, admin: User = Depends(require_admin)) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        return conn.execute(
            """SELECT u.id, u.email, u.display_name FROM user_groups ug JOIN users u ON u.id = ug.user_id
               WHERE ug.group_id = %s ORDER BY u.email""",
            (group_id,),
        ).fetchall()


@router.post("/groups/{group_id}/members", status_code=201)
def add_member(group_id: UUID, body: MemberIn, admin: User = Depends(require_admin)) -> dict[str, str]:
    with pool().connection() as conn:
        conn.execute(
            "INSERT INTO user_groups (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (body.user_id, group_id),
        )
        acl.audit(conn, admin.id, "acl_change", {"user_id": body.user_id, "added_group": group_id})
    return {"status": "ok"}


@router.delete("/groups/{group_id}/members/{user_id}")
def remove_member(group_id: UUID, user_id: UUID, admin: User = Depends(require_admin)) -> dict[str, str]:
    """Takes effect on the member's next request: groups are resolved per request, never cached."""
    with pool().connection() as conn:
        conn.execute("DELETE FROM user_groups WHERE user_id = %s AND group_id = %s", (user_id, group_id))
        acl.audit(conn, admin.id, "acl_change", {"user_id": user_id, "removed_group": group_id})
    return {"status": "ok"}


# --- watched folders ---------------------------------------------------------------------------------------


@router.get("/folders")
def list_folders(admin: User = Depends(require_admin)) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        return conn.execute("SELECT id, path, acl_groups, last_scanned_at FROM folders ORDER BY path").fetchall()


@router.post("/folders", status_code=201)
def add_folder(body: FolderIn, admin: User = Depends(require_admin)) -> dict[str, Any]:
    path = os.path.normcase(os.path.abspath(body.path))
    if not os.path.isdir(path):
        raise HTTPException(400, "path is not a directory visible to the worker")
    with pool().connection() as conn:
        row = conn.execute(
            "INSERT INTO folders (path, acl_groups) VALUES (%s, %s) ON CONFLICT (path) DO NOTHING RETURNING id",
            (path, acl.effective_acl(conn, body.group_ids)),
        ).fetchone()
        if row is None:
            raise HTTPException(409, "folder already mapped")
        # Files under a parent mapping may now belong to this nearer folder: rescan the parents too.
        for f in conn.execute("SELECT id, path FROM folders").fetchall():
            if f["id"] == row["id"] or path.startswith(os.path.normcase(f["path"]) + os.sep):
                jobs.enqueue(conn, "folder_scan", {"folder_id": str(f["id"])})
        acl.audit(conn, admin.id, "acl_change", {"folder_id": row["id"], "path": path, "groups": body.group_ids})
    return {"id": row["id"]}


@router.put("/folders/{folder_id}")
def set_folder_acl(folder_id: UUID, body: AclIn, admin: User = Depends(require_admin)) -> dict[str, str]:
    """Documents and chunks change in the same transaction as the mapping: no revocation window (D17)."""
    with pool().connection() as conn:
        acl.set_folder_acl(conn, folder_id, body.group_ids)
        acl.audit(conn, admin.id, "acl_change", {"folder_id": folder_id, "groups": body.group_ids})
    return {"status": "ok"}


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: UUID, admin: User = Depends(require_admin)) -> dict[str, str]:
    with pool().connection() as conn, conn.transaction():
        conn.execute("DELETE FROM documents WHERE folder_id = %s", (folder_id,))
        conn.execute("DELETE FROM folders WHERE id = %s", (folder_id,))
        acl.audit(conn, admin.id, "acl_change", {"deleted_folder": folder_id})
    return {"status": "ok"}


# --- analytics and health ----------------------------------------------------------------------------------


@router.get("/analytics/queries")
def analytics(days: int = 30, admin: User = Depends(require_admin)) -> dict[str, Any]:
    with pool().connection() as conn:
        summary = conn.execute(
            """SELECT count(*) AS queries,
                      avg(('not_found' = ANY(flags))::int)::float AS not_found_rate,
                      avg(('low_grounding' = ANY(flags))::int)::float AS low_grounding_rate,
                      percentile_cont(0.95) WITHIN GROUP (ORDER BY first_token_ms) AS p95_first_token_ms,
                      percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms,
                      percentile_cont(0.95) WITHIN GROUP (ORDER BY queue_ms) AS p95_queue_ms
               FROM messages WHERE role = 'assistant' AND created_at > now() - make_interval(days => %s)""",
            (days,),
        ).fetchone()
        unanswered = conn.execute(
            """SELECT lower(rewritten_query) AS query, count(*) AS times FROM messages
               WHERE role = 'assistant' AND 'not_found' = ANY(flags) AND created_at > now() - make_interval(days => %s)
               GROUP BY 1 ORDER BY 2 DESC LIMIT 20""",
            (days,),
        ).fetchall()
        feedback = conn.execute(
            "SELECT count(*) FILTER (WHERE rating = 1) AS up, count(*) FILTER (WHERE rating = -1) AS down FROM feedback"
        ).fetchone()
    return {"summary": summary, "top_unanswered": unanswered, "feedback": feedback}


@router.get("/health")
def health(admin: User = Depends(require_admin)) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        with pool().connection() as conn:
            conn.execute("SELECT 1")
            out["database"] = "ok"
            out["jobs"] = conn.execute(
                """SELECT count(*) FILTER (WHERE status = 'queued') AS queued,
                          count(*) FILTER (WHERE status = 'running') AS running,
                          count(*) FILTER (WHERE status = 'failed') AS failed,
                          extract(epoch FROM now() - min(run_after) FILTER (WHERE status = 'queued'
                                  AND run_after <= now()))::int AS oldest_ready_s
                   FROM jobs"""
            ).fetchone()
            out["documents"] = conn.execute(
                "SELECT status, count(*) AS n FROM documents GROUP BY status ORDER BY status"
            ).fetchall()
    except Exception as e:
        out["database"] = f"error: {type(e).__name__}"
    # A worker that is alive drains ready jobs within seconds; a growing oldest_ready_s means it is down or stuck.
    oldest = (out.get("jobs") or {}).get("oldest_ready_s")
    out["worker"] = "ok" if oldest is None or oldest < 120 else "stalled"
    try:
        llm._client().with_options(timeout=5).models.list()
        out["llm"] = "ok"
    except Exception as e:
        out["llm"] = f"error: {type(e).__name__}"
    return out
