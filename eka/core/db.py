from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from eka.core.config import settings

Conn = psycopg.Connection[DictRow]

_pool: ConnectionPool[Conn] | None = None


def _configure(conn: Conn) -> None:
    register_vector(conn)


def pool() -> ConnectionPool[Conn]:
    """Autocommit connections; multi-statement writes wrap themselves in conn.transaction()."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool[Conn](
            settings.database_url,
            min_size=1,
            max_size=settings.db_pool_size,
            kwargs={"row_factory": dict_row, "autocommit": True},
            configure=_configure,
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def schema_statements() -> list[str]:
    """schema.sql split into statements; the file has no semicolons inside strings or comments."""
    sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    return [s.strip() for s in sql.split(";") if s.strip()]
