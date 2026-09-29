# Enterprise Knowledge Assistant (EKA) v0.1

Permission-aware RAG: watched folders and uploads in, cited streamed answers out. A chunk the asker's groups
cannot see never reaches the prompt, the citations or the preview. Design: `Implementations/V0.1 Implementation.md`.

Step-by-step setup, verification checklist and troubleshooting: see [HOW_TO_RUN.md](HOW_TO_RUN.md).

## Layout

| Package | Role |
| --- | --- |
| `eka/core` | config, DB pool, schema, ACL, jobs queue, auth hashing, local models |
| `eka/ingestion` | parsers (PDF, DOCX, XLSX, PPTX, HTML, MD, TXT), folder scanner, raw file store |
| `eka/indexing` | structure-aware chunker, chunk swap |
| `eka/retrieval` | dense + keyword search with the ACL predicate, RRF, cross-encoder re-rank |
| `eka/generation` | OpenAI-compatible LLM client, prompts, citation validation |
| `eka/web` | FastAPI app: auth, query (SSE), admin |
| `eka/worker.py` | ingestion worker entry point |
| `eka/eval.py` | retrieval eval and ablations |
| `frontend/` | React + TypeScript + Vite + Tailwind web app |

Planes import only `core`; `web` and `worker.py` compose them.

## Local setup (Windows, native Postgres)

1. Install PostgreSQL 16 and pgvector 0.8 or later. Then create the database:
   `CREATE DATABASE eka; CREATE USER eka PASSWORD 'eka'; ALTER DATABASE eka OWNER TO eka;`
   pgvector older than 0.8 still works, but ACL-filtered vector search can return fewer results.
2. `copy .env.example .env`, then pick an LLM provider block (Nebius, Gemini, NVIDIA NIM or Ollama) and set its key.
3. `make install`, `make migrate`, `make create-admin`.
4. Run `make api`, `make worker` and `make web` in three terminals. Open http://localhost:5173 (API docs:
   http://localhost:8000/api/docs).
5. The embedding and re-ranker weights (about 150 MB) download on first use.

`make` is not installed on Windows by default. Every target is a single `uv run ...` line in the `Makefile`, so you
can copy it, or install make with `winget install GnuWin32.Make`.

## Web app

Routes: `/chat`, `/chat/:id`, `/account`, and for admins `/admin/documents`, `/admin/folders`, `/admin/groups`,
`/admin/health`. Answers stream in; each `[n]` becomes a numbered source chip that opens the cited passage in a side
panel. The passage is fetched fresh, so a revoked permission applies to old links too. The composer always shows which
groups answers draw from. Fonts are bundled (`@fontsource`), so the app makes no third-party requests.

## Evaluation

`make eval Q=eval/questions.jsonl U=someone@company.test` prints Recall@5, MRR@10 and not-found precision for
dense only, keyword only, hybrid (RRF) and hybrid + re-rank, run as that user's groups. The format is in
`eval/questions.example.jsonl`: relevance is a text snippet the correct chunk contains, so labels survive re-indexing.
Add `--final` once, for the held-out numbers. For the chunk-size ablation, set `CHUNK_TARGET_TOKENS` (256, 400 or
600), re-index, and run again.

## Checks

`make check` runs ruff, mypy, the frontend type check and pytest. The ACL canary matrix (`tests/test_acl_matrix.py`) is the hard gate. It
wipes and rebuilds a throwaway database, so it only runs when `TEST_DATABASE_URL` names a database with `test` in
its name:

```
set TEST_DATABASE_URL=postgresql://eka:eka@localhost:5432/eka_test
make test
```

## Deployment

`deploy/docker-compose.yml`: postgres (pgvector), api, worker, nginx (builds and serves the web app, TLS, SSE unbuffered). Ollama is optional under
the `local-llm` profile. The worker sits on an internal-only network. The api also joins an egress network, so it can
reach the hosted LLM.

## Differences from the implementation draft

- **Hosted LLM by default (changes D10, D11 and the threat model).** The questions and retrieved passages the user
  may see go to the configured provider. The ACL still decides what is sent, but "no text leaves the machine" no
  longer holds unless Ollama is used.
- Embeddings and the re-ranker run through fastembed (ONNX, CPU): the same models, without PyTorch.
- `users.email` is `text` with a unique `lower(email)` index instead of `citext`, so no contrib extension is needed.
- An empty group list is stored as `{admins}` on documents, folders and chunks, so one `&&` filter covers default deny.
- Keyword search ORs the question's terms (`websearch_to_tsquery` ANDs them), so natural-language questions match.
- Job retries: 1, 5 and 25 minute backoff, then `failed` (4 attempts in total).
- `acl_apply` jobs are not needed: ACL edits update documents and chunks in the admin's own transaction.
- `GET /auth/me` returns the user's group names for the chat's access line.
- Added endpoints: `GET /auth/me`, `PUT /documents/{id}/acl` (uploads only), `PUT /folders/{id}`.
