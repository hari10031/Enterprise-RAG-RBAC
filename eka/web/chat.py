"""Query (SSE), stop, conversations, citation preview and feedback."""

import json
import logging
import threading
import time
from collections.abc import Generator, Iterator
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from eka.core import acl
from eka.core.config import settings
from eka.core.db import pool
from eka.generation import llm
from eka.retrieval import search
from eka.web.deps import User, current_user, query_limiter

router = APIRouter(tags=["chat"])
log = logging.getLogger("eka.query")

# Caps concurrent generations so one GPU (or one provider quota) is not oversubscribed.
_llm_slots = threading.BoundedSemaphore(settings.llm_parallel)
# message_id -> (owner, stop flag) for generations in flight
_in_flight: dict[UUID, tuple[UUID, threading.Event]] = {}


class QueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None


class FeedbackIn(BaseModel):
    message_id: UUID
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=2000)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _ms(since: float) -> int:
    return int((time.perf_counter() - since) * 1000)


@router.post("/query")
def query(body: QueryIn, user: User = Depends(current_user)) -> StreamingResponse:
    query_limiter.check(user.id)
    with pool().connection() as conn:
        if body.conversation_id:
            if not conn.execute(
                "SELECT 1 FROM conversations WHERE id = %s AND user_id = %s", (body.conversation_id, user.id)
            ).fetchone():
                raise HTTPException(404, "conversation not found")
            conv_id = body.conversation_id
            history = conn.execute(
                "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY created_at", (conv_id,)
            ).fetchall()
        else:
            conv_id = conn.execute(
                "INSERT INTO conversations (user_id, title) VALUES (%s, %s) RETURNING id",
                (user.id, body.question[:80]),
            ).fetchone()["id"]  # type: ignore[index]
            history = []
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)", (conv_id, body.question)
        )
    message_id = uuid4()
    stop = threading.Event()
    _in_flight[message_id] = (user.id, stop)
    return StreamingResponse(
        _answer(user, conv_id, message_id, body.question, history, stop),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _answer(
    user: User, conv_id: UUID, message_id: UUID, question: str, history: list[dict[str, Any]], stop: threading.Event
) -> Iterator[str]:
    start = time.perf_counter()
    timings: dict[str, int] = {}
    try:
        yield _sse("meta", {"conversation_id": conv_id, "message_id": message_id})
        t = time.perf_counter()
        rewritten = llm.rewrite(history, question)
        timings["rewrite_ms"] = _ms(t)
        hits, stage = search.retrieve(rewritten, user.group_ids)
        timings.update(stage)

        answer, model, queue_ms, first_token_ms = "", None, None, None
        if not hits:  # nothing cleared the re-rank gate: skip the model entirely
            answer = llm.NOT_FOUND
            yield _sse("token", {"text": answer})
        else:
            model = settings.llm_model
            t = time.perf_counter()
            if not _llm_slots.acquire(blocking=False):
                yield _sse("queued", {})
                if not _llm_slots.acquire(timeout=settings.llm_timeout):
                    raise TimeoutError("model busy")
            queue_ms = _ms(t)
            gen: Generator[str, None, None] | None = None
            try:
                gen = llm.stream(llm.build_messages(rewritten, hits))
                for delta in gen:
                    if stop.is_set():
                        break
                    if first_token_ms is None:
                        first_token_ms = _ms(start)
                    answer += delta
                    yield _sse("token", {"text": delta})
            finally:
                if gen is not None:
                    gen.close()  # stops the provider stream when the user pressed stop
                _llm_slots.release()

        clean, citations, flags = llm.validate(answer, hits)
        if stop.is_set():
            flags.append("stopped")
        yield _sse("citations", {"citations": citations, "flags": flags})
        latency_ms = _ms(start)
        with pool().connection() as conn, conn.transaction():
            conn.execute(
                """INSERT INTO messages (id, conversation_id, role, content, rewritten_query, citations, flags, model,
                                         queue_ms, first_token_ms, latency_ms)
                   VALUES (%s, %s, 'assistant', %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    message_id,
                    conv_id,
                    clean,
                    rewritten,
                    Jsonb(citations),
                    flags,
                    model,
                    queue_ms,
                    first_token_ms,
                    latency_ms,
                ),
            )
            acl.audit(
                conn,
                user.id,
                "query",
                {
                    "message_id": message_id,
                    "groups": user.group_ids,
                    "rewritten_query": rewritten,
                    "retrieved": [h.chunk_id for h in hits],
                    "cited": [c["chunk_id"] for c in citations],
                },
            )
        log.info(
            "query",
            extra={
                "fields": {
                    "message_id": message_id,
                    "latency_ms": latency_ms,
                    "queue_ms": queue_ms,
                    "first_token_ms": first_token_ms,
                    **timings,
                }
            },
        )
        yield _sse("done", {"message_id": message_id, "flags": flags})
    except Exception as e:
        log.exception("query failed", extra={"fields": {"message_id": message_id}})
        yield _sse("error", {"message": llm.failure_message(e)})
    finally:
        _in_flight.pop(message_id, None)


@router.post("/query/{message_id}/stop")
def stop_query(message_id: UUID, user: User = Depends(current_user)) -> dict[str, str]:
    entry = _in_flight.get(message_id)
    if entry is None or entry[0] != user.id:
        raise HTTPException(404, "no running answer with that id")
    entry[1].set()
    return {"status": "stopping"}


@router.get("/conversations")
def conversations(user: User = Depends(current_user)) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        return conn.execute(
            "SELECT id, title, created_at FROM conversations WHERE user_id = %s ORDER BY created_at DESC LIMIT 200",
            (user.id,),
        ).fetchall()


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: UUID, user: User = Depends(current_user)) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user.id)
        ).fetchone():
            raise HTTPException(404, "conversation not found")
        return conn.execute(
            "SELECT id, role, content, citations, flags, created_at FROM messages "
            "WHERE conversation_id = %s ORDER BY created_at",
            (conversation_id,),
        ).fetchall()


@router.get("/chunks/{chunk_id}")
def chunk_preview(chunk_id: UUID, user: User = Depends(current_user)) -> dict[str, Any]:
    """Citation preview. The ACL is checked again here, so an old link cannot outlive a revocation."""
    with pool().connection() as conn:
        row = conn.execute(
            """SELECT c.id, c.document_id, c.text, c.heading_path, c.page, d.title
               FROM chunks c JOIN documents d ON d.id = c.document_id
               WHERE c.id = %s AND c.acl_groups && %s::uuid[]""",
            (chunk_id, user.group_ids),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "passage not found")
        acl.audit(conn, user.id, "view_chunk", {"chunk_id": chunk_id, "groups": user.group_ids})
    return row


@router.post("/feedback")
def feedback(body: FeedbackIn, user: User = Depends(current_user)) -> dict[str, str]:
    if body.rating == 0:
        raise HTTPException(422, "rating must be 1 or -1")
    with pool().connection() as conn:
        if not conn.execute(
            """SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id
               WHERE m.id = %s AND c.user_id = %s AND m.role = 'assistant'""",
            (body.message_id, user.id),
        ).fetchone():
            raise HTTPException(404, "message not found")
        conn.execute(
            """INSERT INTO feedback (message_id, user_id, rating, comment) VALUES (%s, %s, %s, %s)
               ON CONFLICT (message_id, user_id) DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment""",
            (body.message_id, user.id, body.rating, body.comment),
        )
    return {"status": "ok"}
