"""End-to-end smoke test against a RUNNING stack (API + worker + database + LLM).

    uv run --env-file .env python scripts/smoke_e2e.py

Needs SMOKE_ADMIN_EMAIL and SMOKE_ADMIN_PASSWORD (an admin account) in the environment or .env, and the worker
running on this machine (it must read the folder this script creates). API_URL defaults to http://localhost:8000.

It creates throwaway groups, users, a watched folder and an upload (all suffixed with a run id), checks every case,
then cleans up. It makes about 6 LLM calls, so it fits a small provider quota. Exit code 0 means every check passed.
"""

import json
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

API = os.environ.get("API_URL", "http://localhost:8000").rstrip("/") + "/api/v1"
RUN = uuid.uuid4().hex[:6]
PASSWORD = f"smoke-pass-{RUN}-long"
CANARY_A = f"CANARY-ALPHA-{RUN}"
CANARY_B = f"CANARY-BRAVO-{RUN}"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  -> {detail}'}")
    return ok


def client() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=180)


def login(email: str, password: str = PASSWORD) -> httpx.Client:
    c = client()
    r = c.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return c


def ask(c: httpx.Client, question: str, conversation_id: str | None = None) -> dict[str, Any]:
    """Runs one question and returns the parsed stream: text, citations, flags, events, raw body."""
    out: dict[str, Any] = {"text": "", "citations": [], "flags": [], "events": [], "raw": "", "error": None}
    with c.stream("POST", "/query", json={"question": question, "conversation_id": conversation_id}) as r:
        out["status"] = r.status_code
        if r.status_code != 200:
            r.read()
            out["raw"] = r.text
            return out
        for chunk in r.iter_text():
            out["raw"] += chunk
    for event, data in re.findall(r"event: (\w+)\ndata: (.*)\n\n", out["raw"]):
        d = json.loads(data)
        out["events"].append(event)
        if event == "meta":
            out.update(conversation_id=d["conversation_id"], message_id=d["message_id"])
        elif event == "token":
            out["text"] += d["text"]
        elif event == "citations":
            out.update(citations=d["citations"], flags=d["flags"])
        elif event == "error":
            out["error"] = d["message"]
    return out


def wait_indexed(admin: httpx.Client, titles: set[str], timeout_s: int = 300) -> dict[str, dict[str, Any]]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        docs = {d["title"]: d for d in admin.get("/documents").json() if d["title"] in titles}
        if len(docs) == len(titles) and all(d["status"] in ("indexed", "failed") for d in docs.values()):
            return docs
        time.sleep(3)
    return {d["title"]: d for d in admin.get("/documents").json() if d["title"] in titles}


def chunk_ids_for(c: httpx.Client, doc_title: str, citations: list[dict[str, Any]]) -> list[str]:
    return [x["chunk_id"] for x in citations if x["title"] == doc_title]


def main() -> int:
    admin_email, admin_pw = os.environ.get("SMOKE_ADMIN_EMAIL"), os.environ.get("SMOKE_ADMIN_PASSWORD")
    if not admin_email or not admin_pw:
        sys.exit("Set SMOKE_ADMIN_EMAIL and SMOKE_ADMIN_PASSWORD (an existing admin account).")
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    root = data_dir / f"smoke_sources_{RUN}"
    created: dict[str, Any] = {"groups": [], "users": [], "folders": []}
    admin = login(admin_email, admin_pw)

    try:
        print("\nService health")
        h = admin.get("/health").json()
        for k in ("database", "llm", "worker"):
            check(f"health: {k}", h.get(k) == "ok", str(h.get(k)))

        print("\nSetup: groups, users, watched folders")
        g = {}
        for name in ("alpha", "bravo"):
            r = admin.post("/groups", json={"name": f"smoke-{name}-{RUN}"})
            g[name] = r.json()["id"]
            created["groups"].append(g[name])
        users = {}
        for name, groups in (("alice", ["alpha"]), ("bob", ["bravo"]), ("carol", [])):
            email = f"{name}-{RUN}@smoke.test"
            r = admin.post(
                "/users",
                json={
                    "email": email,
                    "display_name": name.title(),
                    "password": PASSWORD,
                    "group_ids": [g[x] for x in groups],
                },
            )
            check(f"create user {name}", r.status_code == 201, r.text)
            users[name] = {"id": r.json()["id"], "email": email}
            created["users"].append(users[name]["id"])
        r = admin.post("/users", json={"email": users["alice"]["email"], "display_name": "dup", "password": PASSWORD})
        check("duplicate email rejected (409)", r.status_code == 409, str(r.status_code))
        r = admin.post("/users", json={"email": f"weak-{RUN}@smoke.test", "display_name": "w", "password": "short"})
        check("password under 12 characters rejected (422)", r.status_code == 422, str(r.status_code))

        for name, canary in (("alpha", CANARY_A), ("bravo", CANARY_B)):
            d = root / name
            d.mkdir(parents=True)
            (d / f"{name} policy {RUN}.md").write_text(
                f"# {name.title()} travel policy\n\n## Approval code\n\n"
                f"The approval code for {name} travel requests is {canary}. Requests over 500 euros need a manager.\n",
                encoding="utf-8",
            )
            r = admin.post("/folders", json={"path": str(d), "group_ids": [g[name]]})
            check(f"map folder {name}", r.status_code == 201, r.text)
            created["folders"].append(r.json().get("id"))
        r = admin.post("/folders", json={"path": str(root / "does-not-exist"), "group_ids": []})
        check("mapping a missing folder rejected (400)", r.status_code == 400, str(r.status_code))

        print("\nIngestion")
        titles = {f"alpha policy {RUN}.md", f"bravo policy {RUN}.md"}
        docs = wait_indexed(admin, titles)
        check(
            "folder documents indexed",
            len(docs) == 2 and all(d["status"] == "indexed" for d in docs.values()),
            str({t: d["status"] for t, d in docs.items()}),
        )

        alice, bob, carol = (login(users[n]["email"]) for n in ("alice", "bob", "carol"))

        up = alice.post(
            "/documents",
            files={"file": (f"alice note {RUN}.txt", b"Alice private note.", "text/plain")},
            data={"group_ids": [g["bravo"]]},
        )
        check(
            "non-admin cannot share an upload with a group they are not in (403)",
            up.status_code == 403,
            str(up.status_code),
        )
        up = admin.post("/documents", files={"file": (f"fake {RUN}.pdf", b"MZ\x90\x00not a pdf", "application/pdf")})
        check("renamed executable rejected (415)", up.status_code == 415, str(up.status_code))
        up = admin.post(
            "/documents",
            files={"file": (f"upload {RUN}.md", f"# Upload\n\nUploaded {RUN}.".encode(), "text/markdown")},
            data={"group_ids": [g["alpha"]]},
        )
        check("admin upload accepted (201)", up.status_code == 201, up.text)
        upload_ok = wait_indexed(admin, {f"upload {RUN}.md"}, 180).get(f"upload {RUN}.md", {}).get("status")
        check("upload indexed", upload_ok == "indexed", str(upload_ok))

        print("\nAuthorisation boundaries (no LLM)")
        for path in ("/users", "/groups", "/folders", "/health", "/analytics/queries"):
            r = alice.get(path)
            check(f"non-admin blocked from {path} (403)", r.status_code == 403, str(r.status_code))
        check("anonymous blocked (401)", client().get("/conversations").status_code == 401)
        me = alice.get("/auth/me").json()
        check(
            "/auth/me lists only the user's own groups",
            [x["name"] for x in me["groups"]] == [f"smoke-alpha-{RUN}"],
            str(me["groups"]),
        )
        docs_seen = {d["title"] for d in bob.get("/documents").json()}
        check("document list filtered by ACL", f"alpha policy {RUN}.md" not in docs_seen, str(docs_seen))

        print("\nAnswers and ACL (LLM)")
        a1 = ask(alice, "What is the approval code for alpha travel requests?")
        check("alice gets an answer", a1["status"] == 200 and not a1["error"], a1["error"] or a1["raw"][:200])
        check("alice's answer contains her canary", CANARY_A in a1["text"], a1["text"][:200])
        check("alice's answer is cited", bool(a1["citations"]), str(a1["flags"]))
        check("bravo canary never reaches alice", CANARY_B not in a1["raw"])
        alpha_chunks = chunk_ids_for(alice, f"alpha policy {RUN}.md", a1["citations"])

        b1 = ask(bob, "What is the approval code for alpha travel requests?")
        check("alpha canary never reaches bob (answer, citations, stream)", CANARY_A not in b1["raw"], b1["text"][:200])
        c1 = ask(carol, "What is the approval code for alpha travel requests?")
        check(
            "user in no group gets not-found",
            "not_found" in c1["flags"] and CANARY_A not in c1["raw"],
            f"{c1['flags']} {c1['text'][:120]}",
        )

        print("\nFollow-up rewriting (LLM)")
        if a1.get("conversation_id"):
            a2 = ask(alice, "Above what amount is a manager needed for those requests?", a1["conversation_id"])
            check("follow-up answered", not a2["error"] and "500" in a2["text"], a2["error"] or a2["text"][:200])
            msgs = alice.get(f"/conversations/{a1['conversation_id']}/messages")
            check(
                "conversation history stored", msgs.status_code == 200 and len(msgs.json()) >= 4, str(msgs.status_code)
            )
            check(
                "bob cannot read alice's conversation (404)",
                bob.get(f"/conversations/{a1['conversation_id']}/messages").status_code == 404,
            )

        print("\nCitation preview and revocation (no LLM)")
        if alpha_chunks:
            cid = alpha_chunks[0]
            check("alice can open her cited passage", alice.get(f"/chunks/{cid}").status_code == 200)
            check("bob cannot open alice's passage (404)", bob.get(f"/chunks/{cid}").status_code == 404)
            admin.put(f"/folders/{created['folders'][0]}", json={"group_ids": [g["alpha"], g["bravo"]]})
            check("folder shared with bravo: bob can now open it", bob.get(f"/chunks/{cid}").status_code == 200)
            admin.put(f"/folders/{created['folders'][0]}", json={"group_ids": [g["alpha"]]})
            check("folder unshared: bob blocked again immediately", bob.get(f"/chunks/{cid}").status_code == 404)
            admin.delete(f"/groups/{g['alpha']}/members/{users['alice']['id']}")
            check("alice removed from alpha: blocked immediately", alice.get(f"/chunks/{cid}").status_code == 404)
            a3 = ask(alice, "What is the approval code for alpha travel requests?")
            check("removed member gets no alpha canary", CANARY_A not in a3["raw"], a3["text"][:120])
            admin.post(f"/groups/{g['alpha']}/members", json={"user_id": users["alice"]["id"]})
            check("alice re-added: access restored", alice.get(f"/chunks/{cid}").status_code == 200)
        else:
            check("alpha passage was cited (needed for preview checks)", False, "no alpha citation")

        print("\nStop, feedback, rate limit")
        if a1.get("message_id"):
            check(
                "stopping someone else's answer refused (404)",
                bob.post(f"/query/{a1['message_id']}/stop").status_code == 404,
            )
            r = alice.post("/feedback", json={"message_id": a1["message_id"], "rating": 1})
            check("feedback saved", r.status_code == 200, r.text)
            r = bob.post("/feedback", json={"message_id": a1["message_id"], "rating": -1})
            check("feedback on someone else's answer refused (404)", r.status_code == 404, str(r.status_code))
        statuses = [ask(carol, f"zzqx nonsense {i} {RUN}")["status"] for i in range(11)]
        check("rate limit: 11th question in a minute refused (429)", 429 in statuses, str(statuses))

        print("\nAccounts and sessions (no LLM)")
        r = client().post("/auth/login", json={"email": users["carol"]["email"], "password": "wrong-password-123"})
        check("wrong password refused (401)", r.status_code == 401, str(r.status_code))
        for _ in range(5):
            client().post("/auth/login", json={"email": users["bob"]["email"], "password": "wrong-password-123"})
        r = client().post("/auth/login", json={"email": users["bob"]["email"], "password": PASSWORD})
        check("5 failed logins lock the account, even for the right password", r.status_code == 401, str(r.status_code))
        r = alice.post("/auth/password", json={"current_password": "nope-nope-nope", "new_password": "x" * 14})
        check("password change needs the current password (400)", r.status_code == 400, str(r.status_code))
        admin.delete(f"/users/{users['carol']['id']}")
        check("deactivated user's session ends (401)", carol.get("/conversations").status_code == 401)
        alice.post("/auth/logout")
        check("logout ends the session (401)", alice.get("/conversations").status_code == 401)

        print("\nAnalytics")
        a = admin.get("/analytics/queries").json()
        check("analytics counts answers", (a["summary"]["queries"] or 0) > 0, str(a["summary"]))
    finally:
        print("\nCleanup")
        for fid in created["folders"]:
            if fid:
                admin.delete(f"/folders/{fid}")
        for d in admin.get("/documents").json():
            if RUN in d["title"]:
                admin.put(f"/documents/{d['id']}/acl", json={"group_ids": []})  # admins only; uploads stay
        for uid in created["users"]:
            admin.delete(f"/users/{uid}")
        for gid in created["groups"]:
            admin.delete(f"/groups/{gid}")
        shutil.rmtree(root, ignore_errors=True)
        print("  removed test folders, deactivated test users, deleted test groups")

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
