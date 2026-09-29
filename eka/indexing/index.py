from uuid import UUID

from eka.core import models
from eka.core.config import settings
from eka.core.db import Conn
from eka.indexing.chunker import Chunk, Chunker
from eka.ingestion.parsers import Block


def build_chunks(blocks: list[Block]) -> list[Chunk]:
    return Chunker(
        models.count_tokens,
        settings.chunk_target_tokens,
        settings.chunk_max_tokens,
        settings.chunk_overlap_tokens,
    ).chunk(blocks)


def replace_chunks(conn: Conn, document_id: UUID, chunks: list[Chunk]) -> None:
    """Embeds, then swaps old chunks for new in one transaction so a half-indexed document is never searchable."""
    vectors = models.embed_passages([c.embed_text for c in chunks])
    with conn.transaction():
        # Read the ACL inside the transaction; FOR UPDATE blocks a concurrent ACL edit until the swap commits.
        acl = conn.execute("SELECT acl_groups FROM documents WHERE id = %s FOR UPDATE", (document_id,)).fetchone()[
            "acl_groups"
        ]  # type: ignore[index]
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO chunks (document_id, position, heading_path, text, token_count, page,
                                       acl_groups, embed_model, embedding)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (
                        document_id,
                        i,
                        c.heading_path or None,
                        c.text,
                        c.token_count,
                        c.page,
                        acl,
                        settings.embed_model,
                        v,
                    )
                    for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
                ],
            )
        conn.execute("UPDATE documents SET status = 'indexed', indexed_at = now() WHERE id = %s", (document_id,))
