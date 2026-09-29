"""Group-based access control (D15). Every ACL write goes through here so documents and chunks never disagree."""

import json
from collections.abc import Iterable
from functools import partial
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from eka.core.db import Conn

ADMINS = "admins"
_dumps = partial(json.dumps, default=str)  # audit details carry UUIDs


def admins_group_id(conn: Conn) -> UUID:
    return conn.execute("SELECT id FROM groups WHERE name = %s", (ADMINS,)).fetchone()["id"]  # type: ignore[index]


def user_group_ids(conn: Conn, user_id: UUID) -> list[UUID]:
    rows = conn.execute("SELECT group_id FROM user_groups WHERE user_id = %s", (user_id,)).fetchall()
    return [r["group_id"] for r in rows]  # type: ignore[call-overload]


def effective_acl(conn: Conn, groups: Iterable[UUID]) -> list[UUID]:
    """Default deny: an empty group list means admins only, stored explicitly so one filter covers every case."""
    groups = sorted(set(groups))
    return groups or [admins_group_id(conn)]


def set_document_acl(conn: Conn, document_id: UUID, groups: list[UUID]) -> None:
    acl = effective_acl(conn, groups)
    with conn.transaction():
        conn.execute("UPDATE documents SET acl_groups = %s WHERE id = %s", (acl, document_id))
        conn.execute("UPDATE chunks SET acl_groups = %s WHERE document_id = %s", (acl, document_id))


def set_folder_acl(conn: Conn, folder_id: UUID, groups: list[UUID]) -> None:
    acl = effective_acl(conn, groups)
    with conn.transaction():
        conn.execute("UPDATE folders SET acl_groups = %s WHERE id = %s", (acl, folder_id))
        conn.execute("UPDATE documents SET acl_groups = %s WHERE folder_id = %s", (acl, folder_id))
        conn.execute(
            "UPDATE chunks c SET acl_groups = %s FROM documents d WHERE d.id = c.document_id AND d.folder_id = %s",
            (acl, folder_id),
        )


def audit(conn: Conn, user_id: UUID, action: str, detail: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO audit_log (user_id, action, detail) VALUES (%s, %s, %s)",
        (user_id, action, Jsonb(detail, dumps=_dumps)),
    )
