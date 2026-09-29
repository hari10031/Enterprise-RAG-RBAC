"""All tunables come from environment variables; defaults are the v0.1 values from the implementation draft."""

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql://eka:eka@localhost:5432/eka"))
    db_pool_size: int = field(default_factory=lambda: int(_env("DB_POOL_SIZE", "10")))
    data_dir: str = field(default_factory=lambda: _env("DATA_DIR", "./data"))
    models_dir: str | None = field(default_factory=lambda: os.environ.get("MODELS_DIR"))

    # Any OpenAI-compatible endpoint: Nebius, Gemini, NVIDIA NIM, or local Ollama.
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "http://localhost:11434/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", "none"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "qwen3:8b"))
    llm_parallel: int = field(default_factory=lambda: int(_env("LLM_PARALLEL", "2")))
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "120")))
    llm_temperature: float = field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.2")))
    llm_max_tokens: int = field(default_factory=lambda: int(_env("LLM_MAX_TOKENS", "600")))
    # Optional: "none" turns off Gemini thinking (about 2 s to first word instead of 10+). Unset = not sent.
    llm_reasoning_effort: str | None = field(default_factory=lambda: os.environ.get("LLM_REASONING_EFFORT") or None)

    embed_model: str = field(default_factory=lambda: _env("EMBED_MODEL", "BAAI/bge-small-en-v1.5"))
    rerank_model: str = field(default_factory=lambda: _env("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2"))
    # Cross-encoder logit threshold tau. Placeholder until calibrated on the eval set.
    rerank_threshold: float = field(default_factory=lambda: float(_env("RERANK_THRESHOLD", "-4.0")))

    chunk_target_tokens: int = field(default_factory=lambda: int(_env("CHUNK_TARGET_TOKENS", "400")))
    chunk_max_tokens: int = field(default_factory=lambda: int(_env("CHUNK_MAX_TOKENS", "480")))
    chunk_overlap_tokens: int = field(default_factory=lambda: int(_env("CHUNK_OVERLAP_TOKENS", "60")))

    retrieve_k: int = 50
    rerank_candidates: int = 30
    final_passages: int = 6
    per_document_cap: int = 3
    rrf_k: int = 60

    ocr_enabled: bool = field(default_factory=lambda: _env("OCR_ENABLED", "false").lower() == "true")
    parse_timeout_s: int = field(default_factory=lambda: int(_env("PARSE_TIMEOUT_S", "120")))
    scan_interval_s: int = field(default_factory=lambda: int(_env("SCAN_INTERVAL_S", "300")))
    upload_max_bytes: int = 50 * 1024 * 1024

    session_hours: int = 8
    cookie_secure: bool = field(default_factory=lambda: _env("COOKIE_SECURE", "true").lower() == "true")
    queries_per_minute: int = field(default_factory=lambda: int(_env("QUERIES_PER_MINUTE", "10")))


settings = Settings()
