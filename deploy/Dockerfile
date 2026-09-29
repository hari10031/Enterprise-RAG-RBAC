FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY eka ./eka
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev
RUN useradd --create-home eka && mkdir -p /data /models && chown eka /data /models
USER eka
