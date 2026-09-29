"""Ingestion worker: drains the jobs table and schedules folder scans. Run with `python -m eka.worker`."""

import logging
import multiprocessing
import time
from typing import Any
from uuid import UUID

from eka.core import jobs
from eka.core.config import settings
from eka.core.db import Conn, pool
from eka.core.log import setup_logging
from eka.indexing.index import build_chunks, replace_chunks
from eka.ingestion.parsers import Block, parse
from eka.ingestion.scanner import scan_folder
from eka.ingestion.store import raw_path

log = logging.getLogger("eka.worker")


def parse_with_timeout(path: str, mime: str) -> list[Block]:
    """Parses in a child process so a hostile or pathological file cannot hang or crash the worker."""
    with multiprocessing.get_context("spawn").Pool(1) as p:
        return p.apply_async(parse, (path, mime)).get(timeout=settings.parse_timeout_s)


def ingest(conn: Conn, document_id: UUID) -> None:
    doc = conn.execute(
        "SELECT id, source, mime_type, content_hash FROM documents WHERE id = %s", (document_id,)
    ).fetchone()
    if doc is None:
        return  # deleted since the job was queued

    def status(s: str) -> None:
        conn.execute("UPDATE documents SET status = %s WHERE id = %s", (s, document_id))

    status("parsing")
    blocks = parse_with_timeout(str(raw_path(doc["source"], doc["id"], doc["content_hash"])), doc["mime_type"])
    status("chunking")
    chunks = build_chunks(blocks)
    status("embedding")
    replace_chunks(conn, document_id, chunks)
    log.info("indexed", extra={"fields": {"document_id": str(document_id), "chunks": len(chunks)}})


def handle(conn: Conn, job: dict[str, Any]) -> None:
    if job["kind"] == "ingest":
        ingest(conn, UUID(job["payload"]["document_id"]))
    elif job["kind"] == "folder_scan":
        scan_folder(conn, UUID(job["payload"]["folder_id"]))
    else:
        raise ValueError(f"unknown job kind {job['kind']}")


def schedule_scans(conn: Conn) -> None:
    for f in conn.execute("SELECT id FROM folders").fetchall():
        jobs.enqueue(conn, "folder_scan", {"folder_id": str(f["id"])})


def run_once(conn: Conn) -> bool:
    """Runs one ready job; False when the queue is empty."""
    job = jobs.claim(conn)
    if job is None:
        return False
    try:
        handle(conn, job)
        jobs.complete(conn, job["id"])
    except Exception as e:
        log.exception("job failed", extra={"fields": {"job_id": job["id"], "kind": job["kind"]}})
        final = jobs.fail(conn, job, f"{type(e).__name__}: {e}"[:2000])
        if job["kind"] == "ingest":
            new = "failed" if final else "queued"
            conn.execute("UPDATE documents SET status = %s WHERE id = %s", (new, job["payload"]["document_id"]))
    return True


def main() -> None:
    setup_logging()
    with pool().connection() as conn:
        jobs.requeue_running(conn)
    next_scan = 0.0
    while True:
        with pool().connection() as conn:
            if time.monotonic() >= next_scan:
                schedule_scans(conn)
                next_scan = time.monotonic() + settings.scan_interval_s
            busy = run_once(conn)
        if not busy:
            time.sleep(2)  # ponytail: polling; LISTEN/NOTIFY if the 2 s pickup delay ever matters


if __name__ == "__main__":
    main()
