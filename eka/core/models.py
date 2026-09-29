"""Local CPU models (D4, D5): embedder, its tokenizer and the cross-encoder. Loaded lazily, once per process."""

from functools import cache

import numpy as np

from eka.core.config import settings

# bge-*-v1.5 recommended instruction for retrieval queries; passages get no prefix.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@cache
def _embedder():  # type: ignore[no-untyped-def]
    from fastembed import TextEmbedding

    return TextEmbedding(settings.embed_model, cache_dir=settings.models_dir)


@cache
def _tokenizer():  # type: ignore[no-untyped-def]
    from tokenizers import Tokenizer

    emb = _embedder()
    emb.token_count("load")  # forces the tokenizer to load
    # Copy without the model's 512-token truncation so long texts are counted exactly.
    tok = Tokenizer.from_str(emb.model.tokenizer.to_str())
    tok.no_truncation()
    tok.no_padding()
    return tok


@cache
def _reranker():  # type: ignore[no-untyped-def]
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(settings.rerank_model, cache_dir=settings.models_dir)


def count_tokens(text: str) -> int:
    return len(_tokenizer().encode(text, add_special_tokens=False).ids)


def _normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-12)


def embed_passages(texts: list[str]) -> list[np.ndarray]:
    if not texts:
        return []
    return list(_normalise(np.array(list(_embedder().embed(texts, batch_size=32)), dtype=np.float32)))


def embed_query(text: str) -> np.ndarray:
    vec = np.array(list(_embedder().embed([QUERY_PREFIX + text])), dtype=np.float32)
    return _normalise(vec)[0]


def rerank(query: str, texts: list[str]) -> list[float]:
    """Cross-encoder logits, one per text, in input order."""
    if not texts:
        return []
    return [float(s) for s in _reranker().rerank(query, texts)]
