# Every target is one `uv run` line, so it also works without make (copy the command).
ENV := $(if $(wildcard .env),--env-file .env,)
RUN := uv run $(ENV)

.PHONY: install check lint test test-acl migrate api worker create-admin fmt web web-build eval smoke

install:
	uv sync
	cd frontend && npm install

check: lint test

lint:
	uv run ruff check eka tests migrations
	uv run mypy eka
	cd frontend && npx tsc -b

# DB tests (incl. the ACL matrix) run when TEST_DATABASE_URL points at a throwaway database; otherwise they skip.
test:
	$(RUN) pytest -q

test-acl:
	$(RUN) pytest -q tests/test_acl_matrix.py

migrate:
	$(RUN) alembic upgrade head

api:
	$(RUN) uvicorn eka.web.app:app --reload --port 8000

worker:
	$(RUN) python -m eka.worker

create-admin:
	$(RUN) python -m eka.cli create-admin

fmt:
	uv run ruff check --fix eka tests migrations
	uv run ruff format eka tests migrations

# Web app dev server on http://localhost:5173, proxying /api to `make api`.
web:
	cd frontend && npm run dev

web-build:
	cd frontend && npm run build

# Retrieval eval + ablations: make eval Q=eval/questions.jsonl U=you@company.test
eval:
	$(RUN) python -m eka.eval $(Q) --user $(U)

# End-to-end smoke test against the running stack (api + worker): needs SMOKE_ADMIN_EMAIL / SMOKE_ADMIN_PASSWORD.
smoke:
	$(RUN) python scripts/smoke_e2e.py
