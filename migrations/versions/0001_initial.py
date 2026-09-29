"""Initial v0.1 schema, from eka/core/schema.sql.

Revision ID: 0001
Revises:
"""

from alembic import op

from eka.core.db import schema_statements

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = (
    "sessions",
    "audit_log",
    "jobs",
    "feedback",
    "messages",
    "conversations",
    "chunks",
    "documents",
    "folders",
    "user_groups",
    "users",
    "groups",
)


def upgrade() -> None:
    for statement in schema_statements():
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
