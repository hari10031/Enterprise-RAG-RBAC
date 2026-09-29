"""Watched-folder scan (D16, D17): size and mtime first, SHA-256 only when they changed."""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from eka.core import acl, jobs
from eka.core.db import Conn
from eka.ingestion.parsers import MIME_BY_EXT, UnsupportedFile, sniff_mime
from eka.ingestion.store import save_copy, sha256_file


def norm_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def nearest_folder(path: str, folders: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The mapped folder with the longest path that contains the file."""
    best = None
    for f in folders:
        root = norm_path(f["path"])
        if path.startswith(root + os.sep) and (best is None or len(root) > len(norm_path(best["path"]))):
            best = f
    return best


def scan_folder(conn: Conn, folder_id: UUID) -> None:
    folders = conn.execute("SELECT id, path, acl_groups FROM folders").fetchall()
    folder = next((f for f in folders if f["id"] == folder_id), None)
    if folder is None:
        return
    existing = {
        d["path"]: d
        for d in conn.execute(
            "SELECT id, path, size_bytes, file_mtime, content_hash, acl_groups, folder_id FROM documents "
            "WHERE source = 'folder' AND folder_id = %s",
            (folder_id,),
        ).fetchall()
    }
    seen: set[str] = set()
    for root, _, files in os.walk(folder["path"]):
        for name in files:
            path = norm_path(os.path.join(root, name))
            if Path(name).suffix.lower() not in MIME_BY_EXT or nearest_folder(path, folders) is not folder:
                continue
            seen.add(path)
            try:
                _sync_file(conn, folder, path, name, existing.get(path))
            except (OSError, UnsupportedFile):
                continue  # vanished mid-scan or unreadable; next scan retries

    for path, doc in existing.items():
        if path in seen:
            continue
        owner = nearest_folder(path, folders) if os.path.exists(path) else None
        if owner is None:
            conn.execute("DELETE FROM documents WHERE id = %s", (doc["id"],))  # file deleted: chunks cascade
        else:  # a nested folder was mapped after this file was indexed
            conn.execute("UPDATE documents SET folder_id = %s WHERE id = %s", (owner["id"], doc["id"]))
            acl.set_document_acl(conn, doc["id"], owner["acl_groups"])
    conn.execute("UPDATE folders SET last_scanned_at = now() WHERE id = %s", (folder_id,))


def _sync_file(conn: Conn, folder: dict[str, Any], path: str, name: str, doc: dict[str, Any] | None) -> None:
    """`path` is case-normalised for matching; `name` keeps the file's real spelling for the title."""
    st = os.stat(path)
    mtime = datetime.fromtimestamp(st.st_mtime, UTC)
    if doc is not None and doc["size_bytes"] == st.st_size and doc["file_mtime"] == mtime:
        return
    content_hash = sha256_file(path)
    if doc is not None and doc["content_hash"] == content_hash:
        # Content unchanged: only the ACL check.
        conn.execute(
            "UPDATE documents SET size_bytes = %s, file_mtime = %s WHERE id = %s", (st.st_size, mtime, doc["id"])
        )
        if sorted(doc["acl_groups"]) != sorted(folder["acl_groups"]):
            acl.set_document_acl(conn, doc["id"], folder["acl_groups"])
        return
    with open(path, "rb") as f:
        mime = sniff_mime(path, f.read(8))
    row = conn.execute(
        """INSERT INTO documents (source, folder_id, path, title, mime_type, size_bytes, file_mtime,
                                  content_hash, acl_groups, status)
           VALUES ('folder', %(f)s, %(p)s, %(t)s, %(m)s, %(s)s, %(mt)s, %(h)s, %(acl)s, 'queued')
           ON CONFLICT (source, path) DO UPDATE SET folder_id = EXCLUDED.folder_id, mime_type = EXCLUDED.mime_type,
             size_bytes = EXCLUDED.size_bytes, file_mtime = EXCLUDED.file_mtime,
             content_hash = EXCLUDED.content_hash, title = EXCLUDED.title, status = 'queued'
           RETURNING id""",
        {
            "f": folder["id"],
            "p": path,
            "t": name,
            "m": mime,
            "s": st.st_size,
            "mt": mtime,
            "h": content_hash,
            "acl": acl.effective_acl(conn, folder["acl_groups"]),
        },
    ).fetchone()
    doc_id = row["id"]  # type: ignore[index]
    if doc is None:  # may have moved here from another folder mapping: bring its chunks' ACL along
        acl.set_document_acl(conn, doc_id, folder["acl_groups"])
    save_copy(path, "folder", doc_id, content_hash)
    jobs.enqueue(conn, "ingest", {"document_id": str(doc_id)})
