from dataclasses import dataclass
from uuid import UUID


@dataclass
class Hit:
    """A retrieved passage; shared by retrieval and generation."""

    chunk_id: UUID
    document_id: UUID
    title: str
    heading_path: str | None
    page: int | None
    text: str
    score: float
