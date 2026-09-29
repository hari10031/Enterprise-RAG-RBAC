"""ACL test matrix: the hard gate. Runs the real pipeline (scanner, worker, SQL retrieval, API) against Postgres.

Models are faked so the test needs no downloads, and the fake LLM echoes its whole prompt: any unauthorised chunk
that reaches generation shows up in the answer as a canary.
"""

import hashlib
import json
import os
import re
from collections.abc import Generator, Iterator
from typing import Any

import numpy as np
import pytest

pytestmark = pytest.mark.db
if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)
if "test" not in os.environ["TEST_DATABASE_URL"].rsplit("/", 1)[-1]:
    pytest.skip("refusing to wipe a database whose name does not contain 'test'", allow_module_level=True)

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from eka import cli, worker  # noqa: E402
from eka.core import models  # noqa: E402
from eka.core.config import settings  # noqa: E402
from eka.core.db import close_pool, pool, schema_statements  # noqa: E402
from eka.generation import llm  # noqa: E402
from eka.web.app import app  # noqa: E402

CANARIES = {
    "engineering": "CANARY-ENG-19c2",
    "hr": "CANARY-HR-7f3a",
    "admins": "CANARY-ADM-0b5e",  # a folder mapped with no groups: default deny
}
PASSWORD = "correct horse battery staple"
QUESTIONS = ["What is the leave policy?", "Which canary code applies?", "deployment runbook and salary bands"]


def _fake_vector(text: str) -> np.ndarray:
    v = np.zeros(384, dtype=np.float32)
    for w in re.findall(r"\w+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 384] += 1
    return v / max(float(np.linalg.norm(v)), 1e-6)


def _fake_stream(messages: list[dict[str, str]]) -> Generator[str, None, None]:
    yield messages[-1]["content"] + " [1]"


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    mp = pytest.MonkeyPatch()
    mp.setattr(models, "count_tokens", lambda t: len(t.split()))
    mp.setattr(models, "embed_passages", lambda ts: [_fake_vector(t) for t in ts])
    mp.setattr(models, "embed_query", _fake_vector)
    mp.setattr(models, "rerank", lambda q, ts: [1.0] * len(ts))
    mp.setattr(llm, "stream", _fake_stream)
    mp.setattr(llm, "complete", lambda messages, max_tokens: messages[-1]["content"].rsplit("Last question: ", 1)[-1])
    mp.setattr(worker, "parse_with_timeout", worker.parse)  # no child process in tests

    # Plain connection: the pool registers the vector type, which must exist before the pool opens.
    close_pool()
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        for s in schema_statements():
            conn.execute(s)
        cli.create_admin(conn, "admin@test.local", "Admin", PASSWORD)

    root = tmp_path_factory.mktemp("sources")
    for group, canary in CANARIES.items():
        (root / group).mkdir()
        (root / group / "secret.md").write_text(f"# Leave policy\n\nThe canary code is {canary}. Salary bands apply.")
    (root / "all-staff").mkdir()
    (root / "all-staff" / "handbook.txt").write_text("The leave policy for all staff is 25 days. Deployment runbook.")

    admin = TestClient(app, base_url="https://testserver")
    admin.__enter__()
    _login(admin, "admin@test.local")
    groups = {
        g: admin.post("/api/v1/groups", json={"name": g}).json()["id"] for g in ("engineering", "hr", "all-staff")
    }
    groups["admins"] = next(g["id"] for g in admin.get("/api/v1/groups").json() if g["name"] == "admins")
    users = {}
    for g in ("engineering", "hr", "all-staff"):
        body = {"email": f"{g}@test.local", "display_name": g, "password": PASSWORD, "group_ids": [groups[g]]}
        users[g] = admin.post("/api/v1/users", json=body).json()["id"]
    folders = {}
    for g in ("engineering", "hr", "all-staff"):
        folders[g] = admin.post("/api/v1/folders", json={"path": str(root / g), "group_ids": [groups[g]]}).json()["id"]
    folders["admins"] = admin.post("/api/v1/folders", json={"path": str(root / "admins"), "group_ids": []}).json()["id"]
    _drain()
    yield {"admin": admin, "groups": groups, "users": users, "folders": folders}
    admin.__exit__(None, None, None)
    mp.undo()


def _drain() -> None:
    with pool().connection() as conn:
        while worker.run_once(conn):
            pass


def _login(client: TestClient, email: str) -> None:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text


def _client(email: str) -> TestClient:
    c = TestClient(app, base_url="https://testserver")
    _login(c, email)
    return c


def _ask(client: TestClient, question: str, conversation_id: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    r = client.post("/api/v1/query", json={"question": question, "conversation_id": conversation_id})
    assert r.status_code == 200, r.text
    events = [(m.group(1), json.loads(m.group(2))) for m in re.finditer(r"event: (\w+)\ndata: (.*)\n\n", r.text)]
    assert events[-1][0] == "done", events
    return r.text, [e[1] for e in events]


def _forbidden(user_group: str) -> list[str]:
    return [c for g, c in CANARIES.items() if g != user_group]


def test_everything_indexed(env: dict[str, Any]) -> None:
    docs = env["admin"].get("/api/v1/documents").json()
    assert len(docs) == 4 and all(d["status"] == "indexed" for d in docs), docs


@pytest.mark.parametrize("group", ["engineering", "hr", "all-staff"])
def test_no_canary_reaches_unauthorised_user(env: dict[str, Any], group: str) -> None:
    client = _client(f"{group}@test.local")
    conv = None
    for q in QUESTIONS:
        raw, events = _ask(client, q, conv)
        conv = events[0]["conversation_id"]
        for canary in _forbidden(group):
            assert canary not in raw, f"{canary} leaked to {group} for {q!r}"
        for cite in next(e for e in events if "citations" in e)["citations"]:
            preview = client.get(f"/api/v1/chunks/{cite['chunk_id']}")
            assert preview.status_code == 200
            assert not any(c in preview.text for c in _forbidden(group))
    if group in CANARIES:
        raw, _ = _ask(client, "Which canary code applies?")
        assert CANARIES[group] in raw  # the user's own documents are found
    # Rewritten follow-ups are stored per message; none may carry another group's canary.
    msgs = client.get(f"/api/v1/conversations/{conv}/messages").text
    assert not any(c in msgs for c in _forbidden(group))
    assert all(d["acl_groups"] for d in client.get("/api/v1/documents").json())


def test_direct_chunk_preview_of_forbidden_chunk_is_404(env: dict[str, Any]) -> None:
    with pool().connection() as conn:
        hr_chunk = conn.execute(
            "SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.text LIKE %s",
            (f"%{CANARIES['hr']}%",),
        ).fetchone()["id"]  # type: ignore[index]
    assert _client("engineering@test.local").get(f"/api/v1/chunks/{hr_chunk}").status_code == 404
    assert _client("hr@test.local").get(f"/api/v1/chunks/{hr_chunk}").status_code == 200


def test_admin_sees_default_deny_folder(env: dict[str, Any]) -> None:
    raw, _ = _ask(env["admin"], "Which canary code applies?")
    assert CANARIES["admins"] in raw


def test_revocation_applies_on_next_query(env: dict[str, Any]) -> None:
    admin, groups, users = env["admin"], env["groups"], env["users"]
    hr = _client("hr@test.local")
    assert CANARIES["hr"] in _ask(hr, "Which canary code applies?")[0]

    admin.delete(f"/api/v1/groups/{groups['hr']}/members/{users['hr']}")
    assert CANARIES["hr"] not in _ask(hr, "Which canary code applies?")[0]
    admin.post(f"/api/v1/groups/{groups['hr']}/members", json={"user_id": users["hr"]})
    assert CANARIES["hr"] in _ask(hr, "Which canary code applies?")[0]

    # Folder remap: HR folder shared with all-staff, then taken back, with no re-index in between.
    staff = _client("all-staff@test.local")
    folder = env["folders"]["hr"]
    admin.put(f"/api/v1/folders/{folder}", json={"group_ids": [groups["hr"], groups["all-staff"]]})
    assert CANARIES["hr"] in _ask(staff, "Which canary code applies?")[0]
    admin.put(f"/api/v1/folders/{folder}", json={"group_ids": [groups["hr"]]})
    assert CANARIES["hr"] not in _ask(staff, "Which canary code applies?")[0]


def test_non_admin_blocked_from_admin_endpoints(env: dict[str, Any]) -> None:
    c = _client("engineering@test.local")
    for path in ("/api/v1/users", "/api/v1/groups", "/api/v1/folders", "/api/v1/health", "/api/v1/analytics/queries"):
        assert c.get(path).status_code == 403, path
