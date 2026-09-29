"""API service. Run with `uvicorn eka.web.app:app`."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from eka.core.db import close_pool, pool
from eka.core.log import setup_logging
from eka.web import admin, auth, chat


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    pool()
    yield
    close_pool()


app = FastAPI(
    title="Enterprise Knowledge Assistant",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
for r in (auth.router, chat.router, admin.router):
    app.include_router(r, prefix="/api/v1")


@app.middleware("http")
async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    return response
