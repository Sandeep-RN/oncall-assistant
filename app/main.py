"""On-call assistant API.

- GET  /healthz  liveness only: never touches the database, the model files or the provider.
- POST /ask      a cited answer or a refusal from the team's documents (ADR 0002).

The real answerer (model, database pool, provider) is built at startup when it is configured.
If something is missing, /ask says "not_configured" and /healthz still answers: a liveness probe
must not restart the pod over a dependency (same idea as ADR 0016 in the platform repo).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.answer.service import Answerer, Unavailable

log = logging.getLogger("oncall")


def build_answerer() -> tuple[Answerer, object]:
    """The real wiring: local model, a small Postgres pool, the configured provider."""
    import httpx
    from psycopg_pool import ConnectionPool

    from app.answer.llm import TIMEOUT, LLMSettings, chat
    from app.embed.model import OnnxEmbedder
    from app.index.store import search

    settings = LLMSettings.from_env()
    embedder = OnnxEmbedder()
    # Two connections: one per concurrent answer (Answerer allows two at a time).
    pool = ConnectionPool(os.environ.get("DATABASE_URL", ""), min_size=1, max_size=2, open=True)
    http = httpx.Client(timeout=TIMEOUT)

    def search_pool(vector, k):
        with pool.connection() as conn:
            return search(conn, vector, k=k)

    answerer = Answerer(
        embedder,
        search_pool,
        lambda messages: chat(settings, messages, client=http),
        model=settings.model,
    )
    log.info("answerer ready: provider=%s model=%s", settings.provider, settings.model)
    return answerer, (pool, http)


@asynccontextmanager
async def lifespan(app: FastAPI):
    resources = None
    if app.state.answerer is None and os.environ.get("ONCALL_DISABLE_ANSWERER") != "1":
        try:
            app.state.answerer, resources = build_answerer()
        except Exception as e:  # noqa: BLE001 - any setup failure leaves /ask "not configured"
            log.error("answerer not configured: %s: %s", type(e).__name__, e)
    yield
    if resources:
        pool, http = resources
        pool.close()
        http.close()


app = FastAPI(title="oncall-assistant", lifespan=lifespan)
app.state.answerer = None


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask")
def ask(body: Question):
    # A sync endpoint: FastAPI runs it in its thread pool, so a slow model call does not block
    # the event loop, and the Answerer's own limit of two concurrent calls applies.
    answerer: Answerer | None = app.state.answerer
    if answerer is None:
        return JSONResponse(
            {
                "kind": "unavailable",
                "reason": "not_configured",
                "notice": "The assistant is not configured on this server.",
            },
            status_code=503,
        )
    try:
        result = answerer.ask(body.question.strip())
    except Unavailable as e:
        return JSONResponse(
            {"kind": "unavailable", "reason": e.reason, "notice": e.notice}, status_code=503
        )
    return result.__dict__
