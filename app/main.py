"""On-call assistant API.

- GET  /         the page: one static file with a question box (issue #6, app/page.py).
- GET  /saved    the saved answers (ADR 0003): from a file in the image, nothing else needed.
- GET  /healthz  liveness only: never touches the database, the model files or the provider.
- POST /ask      a cited answer or a refusal from the team's documents (ADR 0002).
- /docs, /redoc, /openapi.json are not served unless ONCALL_ENABLE_API_DOCS=1 (issue #47).

The real answerer (model, database pool, provider) is built at startup when it is configured.
If something is missing, /ask says "not_configured" and /healthz still answers: a liveness probe
must not restart the pod over a dependency (same idea as ADR 0016 in the platform repo).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.answer.service import Answerer, Search, Unavailable
from app.budget.budget import PUBLIC
from app.budget.tokens import DemoTokens
from app.page import load_page
from app.saved.store import SavedAnswers, load_saved

log = logging.getLogger("oncall")

# How long a question waits for a database connection before it gives up with a 503
# "index_unavailable". psycopg_pool waits 30 s by default, far over the 8 s latency target: a
# down Postgres would make every visitor wait before the same clean 503 (issue #31, #6). Embedding
# takes ~0.1 s, so 3 s leaves the answer well inside the target even when the pool is empty.
DB_POOL_TIMEOUT = 3.0


def configure_logging() -> None:
    """Send the app's own log lines (loggers under "oncall") to stderr (issue #26).

    uvicorn configures only its own loggers, so without this the root logger stays at WARNING and
    every INFO line (one per question, from "oncall.ask") is dropped. The level is set on the
    "oncall" logger only: the root stays at WARNING, so third-party libraries (httpx logs every
    provider URL at INFO) stay quiet. A no-op handler-wise if the host already installed one
    (pytest does), so tests keep using caplog.
    """
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s %(message)s")
    name = os.environ.get("ONCALL_LOG_LEVEL", "INFO").strip().upper()
    level = logging.getLevelName(name)
    # getLevelName returns a string ("Level LOUD") for an unknown name: fall back to INFO.
    log.setLevel(level if isinstance(level, int) else logging.INFO)


configure_logging()

# Read at import: a missing or unreadable page file is a broken build and should fail here, not
# on the first visitor. The image smoke test in CI requests it.
PAGE = load_page()


def _load_saved() -> SavedAnswers | None:
    """The saved answers, or None if the file is missing or invalid.

    Unlike the page, a bad file does not stop the app: saved answers are a degradation aid, and the
    app must still start (the build script that REGENERATES the file imports this module, so a
    hard failure here would make a broken file impossible to rebuild). Without them a capacity
    limit is a plain 503. Tests and the image smoke test stop a bad file from shipping.
    """
    try:
        return load_saved()
    except (OSError, ValueError) as e:
        log.error("saved answers not available: %s: %s", type(e).__name__, e)
        return None


SAVED = _load_saved()

# Demo tokens (ADR 0003): a mounted directory of token hashes, read on every lookup so a token added
# or revoked works within about a minute with no restart. Unset or empty means no tokens exist,
# and a request that presents one is refused (401), never treated as the public.
TOKENS = DemoTokens(os.environ.get("DEMO_TOKEN_DIR"))


def open_pool(conninfo: str = "", *, timeout: float = DB_POOL_TIMEOUT):
    """The app's small Postgres pool. A caller that cannot get a connection within `timeout`
    seconds gets psycopg_pool.PoolTimeout, a psycopg error, which /ask turns into a 503."""
    from psycopg_pool import ConnectionPool

    # Two connections: one per concurrent answer (Answerer allows two at a time).
    return ConnectionPool(conninfo, min_size=1, max_size=2, timeout=timeout, open=True)


def pool_search(pool) -> Search:
    """A search function that borrows a connection from the pool for each question."""
    from app.index.store import search

    def search_pool(vector, k):
        with pool.connection() as conn:
            return search(conn, vector, k=k)

    return search_pool


def build_answerer() -> tuple[Answerer, object]:
    """The real wiring: local model, a small Postgres pool, the configured provider."""
    import httpx

    from app.answer.llm import TIMEOUT, LLMSettings, chat
    from app.budget.budget import Budget, BudgetSettings
    from app.budget.ledger import PgLedger
    from app.embed.model import OnnxEmbedder

    settings = LLMSettings.from_env()
    # A bad budget setting stops the answerer (/ask says "not configured") instead of being
    # replaced by a default; CI checks the same values on the ConfigMap.
    budget_settings = BudgetSettings.from_env()
    embedder = OnnxEmbedder()
    pool = open_pool(os.environ.get("DATABASE_URL", ""))
    http = httpx.Client(timeout=TIMEOUT)

    answerer = Answerer(
        embedder,
        pool_search(pool),
        lambda messages: chat(settings, messages, client=http),
        model=settings.model,
        saved=SAVED,
        budget=Budget(PgLedger(pool), budget_settings),
    )
    log.info(
        "answerer ready: provider=%s model=%s budget=%d tokens/day, public %d%%",
        settings.provider,
        settings.model,
        budget_settings.total,
        budget_settings.public_pct,
    )
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


API_DOCS_FLAG = "ONCALL_ENABLE_API_DOCS"


def api_docs_settings() -> dict[str, str | None]:
    """FastAPI's docs and schema routes: off unless ONCALL_ENABLE_API_DOCS=1 (issue #47).

    FastAPI serves /docs, /redoc and /openapi.json by default. /docs loads Swagger UI from a
    third-party CDN, outside the page's CSP, and a public demo needs no API console. Off is the
    default so production needs no setting and a missing variable fails safe; only the exact value
    "1" turns them on, so a typo or "false" cannot open them by accident.
    """
    if os.environ.get(API_DOCS_FLAG) == "1":
        return {}  # FastAPI's defaults: /docs, /redoc, /openapi.json
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


app = FastAPI(title="oncall-assistant", lifespan=lifespan, **api_docs_settings())
app.state.answerer = None


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def page(request: Request) -> Response:
    if request.method == "HEAD":
        # Same headers as GET and no body (RFC 9110); Content-Length says how long GET's body is.
        # Link previews and uptime checks use HEAD, and a 405 looked like a broken site.
        length = str(len(PAGE.html.encode()))
        return Response(
            headers={**PAGE.headers, "Content-Length": length},
            media_type="text/html; charset=utf-8",
        )
    return HTMLResponse(PAGE.html, headers=PAGE.headers)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/saved")
def saved():
    """The saved answers, for the page to show after a 503 (a fault) as well. Needs no database,
    no model and no provider."""
    if SAVED is None:
        return JSONResponse(
            {
                "kind": "unavailable",
                "reason": "not_configured",
                "notice": "There are no saved answers on this server.",
            },
            status_code=503,
        )
    return {"saved": SAVED.all()}


@app.post("/ask")
def ask(body: Question, x_demo_token: str | None = Header(default=None)):
    # A sync endpoint: FastAPI runs it in its thread pool, so a slow model call does not block
    # the event loop, and the Answerer's own limit of two concurrent calls applies.
    #
    # Who is asking (ADR 0003): "public", or the NAME of a demo token. A blank header is the
    # public. A token that matches none is a 401 and never a silent downgrade to the public budget:
    # someone who was given a token should be told it does not work. A 401 is the client's
    # mistake, so it is outside the availability target, like a 422.
    who = PUBLIC
    if x_demo_token is not None and x_demo_token.strip():
        name = TOKENS.identify(x_demo_token)
        if name is None:
            logging.getLogger("oncall.ask").info("ask kind=unauthorized reason=unknown_token")
            return JSONResponse(
                {
                    "kind": "unauthorized",
                    "notice": "That demo token is not recognised. Check it, or clear the box to"
                    " ask as a visitor.",
                },
                status_code=401,
            )
        who = name
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
        result = answerer.ask(body.question.strip(), who)
    except Unavailable as e:
        return JSONResponse(
            {"kind": "unavailable", "reason": e.reason, "notice": e.notice}, status_code=503
        )
    return result.__dict__
