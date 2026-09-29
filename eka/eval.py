"""Retrieval evaluation and ablations (evaluation plan). `python -m eka.eval questions.jsonl --user someone@corp`.

Each JSONL line: {"id": "q1", "question": "...", "split": "tune" | "final", "answerable": true,
                  "relevant": ["text that appears in a correct chunk", ...]}
A chunk counts as relevant when it contains any `relevant` string (case-insensitive), so labels survive re-indexing.
The `final` split is reported only with --final, and should be run once, for the reported numbers.
"""

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from eka.core import acl, models
from eka.core.config import settings
from eka.core.db import close_pool, pool
from eka.retrieval import search


@dataclass
class Question:
    id: str
    question: str
    answerable: bool
    relevant: list[str]
    split: str = "tune"


def is_relevant(text: str, needles: list[str]) -> bool:
    low = text.lower()
    return any(n.lower() in low for n in needles)


def recall_at(ranked: list[bool], k: int) -> float:
    return 1.0 if any(ranked[:k]) else 0.0


def reciprocal_rank(ranked: list[bool], k: int) -> float:
    return next((1.0 / (i + 1) for i, hit in enumerate(ranked[:k]) if hit), 0.0)


def summarise(per_question: list[tuple[Question, list[bool], bool]]) -> dict[str, float | None]:
    """per_question: (question, relevance of each ranked chunk, whether the pipeline declined to answer)."""
    answerable = [(q, r) for q, r, _ in per_question if q.answerable]
    unanswerable = [declined for q, _, declined in per_question if not q.answerable]
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    return {
        "recall@5": mean([recall_at(r, 5) for _, r in answerable]),
        "mrr@10": mean([reciprocal_rank(r, 10) for _, r in answerable]),
        "not_found_precision": mean([1.0 if d else 0.0 for d in unanswerable]),
    }


def _texts(ids: list[UUID], groups: list[UUID]) -> dict[UUID, str]:
    with pool().connection() as conn:
        rows = conn.execute(
            "SELECT id, coalesce(heading_path || E'\\n', '') || text AS t FROM chunks "
            "WHERE id = ANY(%s) AND acl_groups && %s::uuid[]",
            (ids, groups),
        ).fetchall()
    return {r["id"]: r["t"] for r in rows}


def _pipelines(groups: list[UUID]) -> dict[str, Callable[[str], tuple[list[str], bool]]]:
    """Each returns (ranked chunk texts, declined). Only the full pipeline can decline (the re-rank gate)."""
    k = settings.retrieve_k

    def ranked_texts(ids: list[UUID]) -> list[str]:
        texts = _texts(ids, groups)
        return [texts[i] for i in ids if i in texts]

    def dense(q: str) -> tuple[list[str], bool]:
        return ranked_texts([c for c, _ in search.dense_search(models.embed_query(q), groups, k)]), False

    def keyword(q: str) -> tuple[list[str], bool]:
        return ranked_texts([c for c, _ in search.keyword_search(q, groups, k)]), False

    def fused(q: str) -> list[UUID]:
        lists = [search.dense_search(models.embed_query(q), groups, k), search.keyword_search(q, groups, k)]
        return search.rrf(lists, settings.rrf_k, settings.per_document_cap, settings.rerank_candidates)

    def hybrid(q: str) -> tuple[list[str], bool]:
        return ranked_texts(fused(q)), False

    def hybrid_rerank(q: str) -> tuple[list[str], bool]:
        texts = ranked_texts(fused(q))
        scored = sorted(zip(models.rerank(q, texts), texts, strict=True), key=lambda p: -p[0])
        kept = [t for s, t in scored if s >= settings.rerank_threshold]
        # Rank by re-rank score, but judge "declined" by the gate, exactly as the API does.
        return [t for _, t in scored], not kept

    return {"dense only": dense, "keyword only": keyword, "hybrid (RRF)": hybrid, "hybrid + re-rank": hybrid_rerank}


def load(path: Path, final: bool) -> list[Question]:
    qs = [Question(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [q for q in qs if (q.split == "final") == final]


def run(questions: list[Question], groups: list[UUID]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for name, pipeline in _pipelines(groups).items():
        per_q = []
        for q in questions:
            texts, declined = pipeline(q.question)
            per_q.append((q, [is_relevant(t, q.relevant) for t in texts], declined))
        results[name] = summarise(per_q)
    return results


def table(results: dict[str, dict[str, Any]]) -> str:
    fmt = lambda v: "n/a" if v is None else f"{v:.3f}"  # noqa: E731
    lines = ["| Pipeline | Recall@5 | MRR@10 | Not-found precision |", "| --- | --- | --- | --- |"]
    for name, m in results.items():
        nf = fmt(m["not_found_precision"]) if name == "hybrid + re-rank" else "n/a"
        lines.append(f"| {name} | {fmt(m['recall@5'])} | {fmt(m['mrr@10'])} | {nf} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("questions", type=Path)
    parser.add_argument("--user", required=True, help="email of the account whose groups the eval runs as")
    parser.add_argument("--final", action="store_true", help="use the held-out final split (run once)")
    args = parser.parse_args()
    with pool().connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE lower(email) = lower(%s)", (args.user,)).fetchone()
        if row is None:
            raise SystemExit(f"no user {args.user}")
        groups = acl.user_group_ids(conn, row["id"])
    questions = load(args.questions, args.final)
    print(
        f"{len(questions)} questions ({'final' if args.final else 'tune'} split), as {args.user}, "
        f"chunk target {settings.chunk_target_tokens} tokens, tau {settings.rerank_threshold}\n"
    )
    try:
        print(table(run(questions, groups)))
    finally:
        close_pool()


if __name__ == "__main__":
    main()
