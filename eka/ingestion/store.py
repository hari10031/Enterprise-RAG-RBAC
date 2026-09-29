"""Raw file store on a local volume (D21): raw/{source}/{document_id}/{hash}."""

import hashlib
import shutil
from pathlib import Path
from uuid import UUID

from eka.core.config import settings


def raw_path(source: str, document_id: UUID, content_hash: str) -> Path:
    return Path(settings.data_dir) / "raw" / source / str(document_id) / content_hash


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def save_copy(src: str | Path, source: str, document_id: UUID, content_hash: str) -> None:
    dest = raw_path(source, document_id, content_hash)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def save_bytes(data: bytes, source: str, document_id: UUID, content_hash: str) -> None:
    dest = raw_path(source, document_id, content_hash)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
