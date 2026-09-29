"""Postgres table as job queue (D9)."""

from typing import Any

from psycopg.types.json import Jsonb

from eka.core.db import Conn

BACKOFF_MINUTES = (1, 5, 25)  # after the 1st, 2nd, 3rd failure; the 4th failure is final


def enqueue(conn: Conn, kind: str, payload: dict[str, Any]) -> None:
    """Skips the insert when an identical job is already waiting."""
    conn.execute(
        """INSERT INTO jobs (kind, payload) SELECT %(k)s, %(p)s
           WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE status = 'queued' AND kind = %(k)s AND payload = %(p)s)""",
        {"k": kind, "p": Jsonb(payload)},
    )


def claim(conn: Conn) -> dict[str, Any] | None:
    return conn.execute(
        """UPDATE jobs SET status = 'running', attempts = attempts + 1
           WHERE id = (SELECT id FROM jobs WHERE status = 'queued' AND run_after <= now()
                       ORDER BY run_after FOR UPDATE SKIP LOCKED LIMIT 1)
           RETURNING id, kind, payload, attempts"""
    ).fetchone()  # type: ignore[return-value]


def complete(conn: Conn, job_id: int) -> None:
    conn.execute("UPDATE jobs SET status = 'done', last_error = NULL WHERE id = %s", (job_id,))


def fail(conn: Conn, job: dict[str, Any], error: str) -> bool:
    """Schedules a retry with backoff; returns True when the job has failed for good."""
    attempts = job["attempts"]
    if attempts > len(BACKOFF_MINUTES):
        conn.execute("UPDATE jobs SET status = 'failed', last_error = %s WHERE id = %s", (error, job["id"]))
        return True
    conn.execute(
        """UPDATE jobs SET status = 'queued', last_error = %s,
           run_after = now() + make_interval(mins => %s) WHERE id = %s""",
        (error, BACKOFF_MINUTES[attempts - 1], job["id"]),
    )
    return False


def requeue_running(conn: Conn) -> None:
    # ponytail: assumes one worker process; with several, only requeue jobs whose worker heartbeat expired.
    conn.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")
