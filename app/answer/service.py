"""Answer one question: retrieve, ask the model, check the citations (ADR 0002).

The parts are passed in (embedder, search, model call), so tests replace any of them and the app
wires the real ones at startup.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import psycopg

from app.answer.llm import Completion, LLMError
from app.answer.prompt import build_messages, parse_answer
from app.embed.model import Embedder
from app.index.store import Hit
from app.saved.store import SavedAnswers

log = logging.getLogger("oncall.ask")

Search = Callable[[np.ndarray, int], Sequence[Hit]]
ModelCall = Callable[[list[dict[str, str]]], Completion]

# What a visitor reads when there is NO live answer and nothing saved to show (503, a fault).
NOTICES = {
    "rate_limited": "The free model tier is busy right now. Please try again in a minute.",
    "timeout": "The model did not answer in time. Please try again.",
    "busy": "Too many questions at once. Please try again in a few seconds.",
    "index_unavailable": "The document index is not available right now. Please try again later.",
}
DEFAULT_NOTICE = "Live answers are unavailable right now. Please try again later."

# Capacity limits (ADR 0003): the free tier doing what it was always going to do. These answer
# 200 with saved answers, which count as a good response. Everything else is a fault and stays
# 503, so the availability target can still burn. "budget_spent" joins this set with the budget.
CAPACITY_REASONS = frozenset({"rate_limited", "busy"})
SAVED_NOTICES = {
    "rate_limited": "The free model tier is at its limit for this minute, so there is no live"
    " answer right now. Here are saved answers to common questions.",
    "busy": "Too many questions are being answered at once, so there is no live answer right"
    " now. Here are saved answers to common questions.",
}
DEFAULT_SAVED_NOTICE = (
    "Live answers are paused right now. Here are saved answers to common questions."
)


class Unavailable(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
        self.notice = NOTICES.get(reason, DEFAULT_NOTICE)


@dataclass
class Answer:
    kind: str  # "live" or "refusal"
    answer: str
    citations: list[dict] = field(default_factory=list)
    reason: str | None = None
    model: str = ""
    timings_ms: dict[str, int] = field(default_factory=dict)
    tokens: dict[str, int] = field(default_factory=dict)


@dataclass
class SavedReply:
    """No live answer because of a capacity limit: the saved answers, and which one (if any) is
    the visitor's own question. The page labels them as saved."""

    reason: str
    notice: str
    match: str | None
    saved: list[dict]
    kind: str = "saved"


def question_hash(question: str) -> str:
    """What the logs keep instead of the question (the brief: questions are not stored)."""
    return hashlib.sha256(question.encode()).hexdigest()[:12]


class Answerer:
    def __init__(
        self,
        embedder: Embedder,
        search: Search,
        llm: ModelCall,
        *,
        model: str,
        k: int = 5,
        max_concurrent: int = 2,
        saved: SavedAnswers | None = None,
    ):
        self.embedder, self.search, self.llm, self.model, self.k = embedder, search, llm, model, k
        # Without saved answers a capacity limit is a plain 503, as in ADR 0002.
        self.saved = saved
        # Bounds memory in a 320Mi pod and calls against a 30-a-minute provider limit.
        self._slots = threading.BoundedSemaphore(max_concurrent)

    def ask(self, question: str) -> Answer | SavedReply:
        if not self._slots.acquire(blocking=False):
            return self._capacity(question, "busy")
        try:
            return self._ask(question)
        finally:
            self._slots.release()

    def _capacity(self, question: str, reason: str) -> SavedReply:
        """A capacity limit: the saved answers (200), or Unavailable (503) if there are none."""
        if self.saved is None:
            self._log(question, "unavailable", reason=reason)
            raise Unavailable(reason)
        self._log(question, "saved", reason=reason)
        return SavedReply(
            reason=reason,
            notice=SAVED_NOTICES.get(reason, DEFAULT_SAVED_NOTICE),
            match=self.saved.match(question),
            saved=self.saved.all(),
        )

    def _ask(self, question: str) -> Answer | SavedReply:
        t0 = time.perf_counter()
        vector = self.embedder.embed_query(question)
        try:
            hits = list(self.search(vector, self.k))
        except psycopg.Error as e:
            # An empty database before the first index run (UndefinedTable) or a Postgres outage
            # (OperationalError, incl. a pool timeout). Log the error class only: no traceback
            # and no message text, which could echo query parameters.
            self._log(question, "unavailable", reason="index_unavailable", error=type(e).__name__)
            raise Unavailable("index_unavailable") from e
        t1 = time.perf_counter()
        timings = {"retrieve": round((t1 - t0) * 1000)}
        if not hits:  # an empty index: nothing to answer from, no model call
            timings["generate"] = 0
            self._log(question, "refusal", reason="no_passages", timings=timings)
            return Answer(
                "refusal",
                "I don't know.",
                reason="no_passages",
                model=self.model,
                timings_ms=timings,
            )
        try:
            completion = self.llm(build_messages(question, hits))
        except LLMError as e:
            if e.reason in CAPACITY_REASONS:
                return self._capacity(question, e.reason)
            self._log(question, "unavailable", reason=e.reason)
            raise Unavailable(e.reason) from e
        timings["generate"] = round((time.perf_counter() - t1) * 1000)
        parsed = parse_answer(completion.text, k=len(hits))
        citations = [
            {
                "n": n,
                "url": hits[n - 1].url,
                "repo": hits[n - 1].repo,
                "path": hits[n - 1].path,
                "title": " > ".join(hits[n - 1].heading_path),
            }
            for n in parsed.cited
        ]
        tokens = {"prompt": completion.prompt_tokens, "completion": completion.completion_tokens}
        self._log(question, parsed.kind, reason=parsed.reason, timings=timings, tokens=tokens)
        return Answer(
            parsed.kind, parsed.answer, citations, parsed.reason, self.model, timings, tokens
        )

    def _log(
        self, question: str, kind: str, *, reason=None, timings=None, tokens=None, error=None
    ) -> None:
        log.info(
            "ask q_hash=%s q_len=%d kind=%s reason=%s timings_ms=%s tokens=%s error=%s",
            question_hash(question),
            len(question),
            kind,
            reason,
            timings,
            tokens,
            error,
        )
