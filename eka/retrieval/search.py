"""Hybrid retrieval. Every query that touches chunks carries the caller's group ids (D15)."""

import time
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from uuid import UUID

import numpy as np

from eka.core import models
from eka.core.config import settings
from eka.core.db import pool
from eka.core.types import Hit

_DENSE_SQL = """
WITH r AS MATERIALIZED (
  SELECT id, document_id, embedding <=> %(v)s AS dist FROM chunks
  WHERE acl_groups && %(g)s::uuid[]
  ORDER BY dist LIMIT %(k)s
)
SELECT id, document_id FROM r ORDER BY dist"""

# websearch_to_tsquery ANDs every term; OR them instead so a question matches chunks sharing most of its words.
_KEYWORD_SQL = """
SELECT c.id, c.document_id
FROM chunks c, CAST(replace(websearch_to_tsquery('english', %(q)s)::text, ' & ', ' | ') AS tsquery) q
WHERE c.tsv @@ q AND c.acl_groups && %(g)s::uuid[]
ORDER BY ts_rank_cd(c.tsv, q) DESC LIMIT %(k)s"""

_FETCH_SQL = """
SELECT c.id, c.document_id, c.text, c.heading_path, c.page, d.title
FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE c.id = ANY(%(ids)s) AND c.acl_groups && %(g)s::uuid[]"""

Ranked = list[tuple[UUID, UUID]]  # (chunk_id, document_id), best first


@cache
def _has_iterative_scan() -> bool:
    with pool().connection() as conn:
        row = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    return row is not None and tuple(int(x) for x in row["extversion"].split(".")[:2]) >= (0, 8)


def dense_search(vector: np.ndarray, groups: list[UUID], k: int) -> Ranked:
    with pool().connection() as conn, conn.transaction():
        conn.execute("SET LOCAL hnsw.ef_search = 100")
        # pgvector 0.8+: keep scanning when the ACL filter drops rows, so small groups still get k results.
        # Older pgvector still works, but filtered queries can return fewer than k rows.
        if _has_iterative_scan():
            conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        rows = conn.execute(_DENSE_SQL, {"v": vector, "g": groups, "k": k}).fetchall()
    return [(r["id"], r["document_id"]) for r in rows]


def keyword_search(query: str, groups: list[UUID], k: int) -> Ranked:
    with pool().connection() as conn:
        rows = conn.execute(_KEYWORD_SQL, {"q": query, "g": groups, "k": k}).fetchall()
    return [(r["id"], r["document_id"]) for r in rows]


def rrf(lists: list[Ranked], k: int = 60, per_document: int = 3, limit: int = 30) -> list[UUID]:
    """Reciprocal rank fusion; at most `per_document` chunks from any one document survive."""
    scores: dict[UUID, float] = {}
    doc_of: dict[UUID, UUID] = {}
    for ranked in lists:
        for rank, (chunk_id, doc_id) in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            doc_of[chunk_id] = doc_id
    out: list[UUID] = []
    per_doc: dict[UUID, int] = {}
    for chunk_id in sorted(scores, key=lambda c: -scores[c]):
        d = doc_of[chunk_id]
        if per_doc.get(d, 0) < per_document:
            per_doc[d] = per_doc.get(d, 0) + 1
            out.append(chunk_id)
            if len(out) == limit:
                break
    return out


def retrieve(query: str, groups: list[UUID]) -> tuple[list[Hit], dict[str, int]]:
    """Returns the passages for generation (possibly none) and per-stage timings in ms."""
    timings: dict[str, int] = {}

    def timed(name: str, fn, *args):  # type: ignore[no-untyped-def]
        t = time.perf_counter()
        out = fn(*args)
        timings[name] = int((time.perf_counter() - t) * 1000)
        return out

    if not groups:
        return [], timings
    k = settings.retrieve_k
    with ThreadPoolExecutor(2) as ex:
        kw = ex.submit(timed, "keyword_ms", keyword_search, query, groups, k)
        vector = timed("embed_ms", models.embed_query, query)
        dense = timed("dense_ms", dense_search, vector, groups, k)
        keyword = kw.result()
    ids = rrf([dense, keyword], settings.rrf_k, settings.per_document_cap, settings.rerank_candidates)
    if not ids:
        return [], timings

    with pool().connection() as conn:
        rows = {r["id"]: r for r in conn.execute(_FETCH_SQL, {"ids": ids, "g": groups}).fetchall()}
    candidates = [rows[i] for i in ids if i in rows]
    texts = [f"{r['heading_path']}\n{r['text']}" if r["heading_path"] else r["text"] for r in candidates]
    scores = timed("rerank_ms", models.rerank, query, texts)
    ranked = sorted(zip(candidates, scores, strict=True), key=lambda p: -p[1])
    hits = [
        Hit(r["id"], r["document_id"], r["title"], r["heading_path"], r["page"], r["text"], s)
        for r, s in ranked
        if s >= settings.rerank_threshold
    ][: settings.final_passages]
    return hits, timings
