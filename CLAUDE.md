# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

EKA (Enterprise Knowledge Assistant) v0.1: permission-aware RAG. Folders and uploads are ingested, and answers stream back with citations. The core invariant: a chunk the asker's groups cannot see never reaches the prompt, the citations or the preview. Design doc: `Implementations/V0.1 Implementation.md` (decisions are cited in code as `D9`, `D15`, and so on). README.md has a "Differences from the implementation draft" section. Setup and troubleshooting: HOW_TO_RUN.md.

## Commands

Dev machine is Windows; `make` may be missing. Every Makefile target is one `uv run ...` line, so copy it from `Makefile` if needed. `$(RUN)` = `uv run --env-file .env` when `.env` exists.

- Install: `make install` (`uv sync` + `npm install` in `frontend/`)
- Run (three terminals): `make api` (uvicorn on :8000, docs at `/api/docs`), `make worker`, `make web` (Vite on :5173, proxies `/api`)
- DB: `make migrate` (alembic), `make create-admin`
- Lint/typecheck: `make lint` (ruff + mypy on `eka` + `npx tsc -b` in frontend). Format: `make fmt`
- All checks: `make check`
- Tests: `make test`. Single test: `uv run --env-file .env pytest -q tests/test_chunker.py::test_name`
- Non-DB tests only (as pre-commit runs): `uv run pytest -q -m "not db"`
- Eval: `make eval Q=eval/questions.jsonl U=user@company.test` (add `--final` for held-out numbers)

DB tests (`pytestmark = pytest.mark.db`, including the ACL canary matrix `tests/test_acl_matrix.py`) skip unless `TEST_DATABASE_URL` is set. The matrix wipes and rebuilds the database, so it runs only when the database name contains `test` (e.g. `postgresql://eka:eka@localhost:5432/eka_test`). `tests/conftest.py` copies `TEST_DATABASE_URL` into `DATABASE_URL` before any `eka` import. The ACL matrix is the hard gate for any change that touches retrieval, ACLs or chunk access.

## Architecture

Python package `eka/`. Planes (`ingestion`, `indexing`, `retrieval`, `generation`) import only `eka/core`. `eka/web` and `eka/worker.py` compose them. Keep that rule.

- **ACL model (`eka/core/acl.py`)**: groups-only RBAC. `acl_groups uuid[]` is denormalised onto `folders`, `documents` and `chunks`. An empty group list is stored as `{admins}` (default deny), so a single `acl_groups && %(g)s::uuid[]` predicate covers every case. Every ACL write must go through `set_document_acl` / `set_folder_acl`. Both update chunks in the same transaction. There is no async ACL job.
- **Retrieval (`eka/retrieval/search.py`)**: dense (pgvector HNSW) and keyword (tsvector, query terms ORed rather than ANDed) searches run in parallel. Results are fused with RRF, then re-ranked by a cross-encoder with a threshold (`RERANK_THRESHOLD`), with a per-document cap. Every SQL query touching `chunks` must carry the caller's group ids. pgvector 0.8+ `hnsw.iterative_scan` is enabled when available.
- **Ingestion (`eka/worker.py`, `eka/core/jobs.py`)**: the Postgres `jobs` table is the queue (`FOR UPDATE SKIP LOCKED`). Job kinds are `ingest` and `folder_scan`. Retries back off at 1, 5 and 25 minutes, then the job is `failed`. Parsing runs in a spawned child process with a timeout. A document moves through statuses `parsing`, `chunking`, `embedding`, and `replace_chunks` swaps its chunks. The worker assumes a single process (`requeue_running` on startup).
- **Generation (`eka/generation/llm.py`)**: any OpenAI-compatible endpoint (Nebius, Gemini, NVIDIA NIM, Ollama), configured via `LLM_*` env vars. `llm.validate` checks `[n]` citations against the retrieved hits.
- **Web (`eka/web`)**: FastAPI. `chat.py` streams answers over SSE (rewrite question, `search.retrieve(..., user.group_ids)`, LLM, validate). The chunk preview endpoint re-checks the ACL on every fetch, so revoked access also applies to old links. Auth uses session cookies and argon2. Admin endpoints are in `admin.py`, dependencies in `deps.py`.
- **Local models (`eka/core/models.py`)**: embeddings (`BAAI/bge-small-en-v1.5`) and re-ranker run via fastembed (ONNX, CPU, no PyTorch). Weights download on first use into `MODELS_DIR`.
- **Config (`eka/core/config.py`)**: a single frozen `settings` dataclass, read from environment variables. Some tunables (`retrieve_k`, `final_passages`, and others) are constants, not env vars.
- **Schema**: `eka/core/schema.sql` is the source of truth. Migration `0001_initial` executes that file at upgrade time (split on `;`, so do not put semicolons inside strings or comments). Editing `schema.sql` therefore changes what 0001 creates. Put schema changes for existing databases in a new alembic revision.
- **Frontend (`frontend/`)**: React, TypeScript, Vite and Tailwind. API client is in `src/api.ts`, auth context in `src/auth.tsx`. Fonts are bundled, so the app makes no third-party requests.
- **Deploy (`deploy/`)**: docker-compose with postgres (pgvector), api, worker and nginx (serves the built frontend, TLS, unbuffered SSE). Ollama is under the `local-llm` profile. The worker is on an internal-only network.

## Conventions

- Ruff line length is 120. Rules: E, F, I, B, UP. mypy uses `check_untyped_defs`.
- Deliberate shortcuts are marked with `# ponytail:` comments that state the limit and the upgrade path.
