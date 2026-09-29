"""Operator commands. `python -m eka.cli create-admin`."""

import argparse
import getpass
import sys

from eka.core import acl
from eka.core.db import Conn, close_pool, pool
from eka.core.security import MIN_PASSWORD_LENGTH, hash_password


def create_admin(conn: Conn, email: str, display_name: str, password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    with conn.transaction():
        user_id = conn.execute(
            """INSERT INTO users (email, display_name, password_hash) VALUES (%s, %s, %s)
               ON CONFLICT (lower(email)) DO UPDATE SET password_hash = EXCLUDED.password_hash, is_active = true
               RETURNING id""",
            (email, display_name, hash_password(password)),
        ).fetchone()["id"]  # type: ignore[index]
        conn.execute(
            "INSERT INTO user_groups (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (user_id, acl.admins_group_id(conn)),
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="eka")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create-admin", help="create or reset an administrator account")
    parser.parse_args()

    email = input("Admin email: ").strip()
    name = input("Display name: ").strip() or email
    password = getpass.getpass(f"Password ({MIN_PASSWORD_LENGTH}+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("passwords do not match")
    with pool().connection() as conn:
        create_admin(conn, email, name, password)
    close_pool()
    print(f"admin {email} ready")


if __name__ == "__main__":
    main()
