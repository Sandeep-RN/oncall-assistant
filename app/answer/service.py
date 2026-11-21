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

from app.answer.llm import Completion, LLMError
from app.answer.prompt import build_messages, parse_answer
from app.embed.model import Embedder
from app.index.store import Hit

log = logging.getLogger("oncall.ask")

Search = Callable[[np.ndarray, int], Sequence[Hit]]
ModelCall = Callable[[list[dict[str, str]]], Completion]

NOTICES = {
    "rate_limited": "The free model tier is busy right now. Please try again in a minute.",
    "timeout": "The model did not answer in time. Please try again.",
    "busy": "Too many questions at once. Please try again in a few seconds.",
}
DEFAULT_NOTICE = "Live answers are unavailable right now. Please try again later."


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
    ):
        self.embedder, self.search, self.llm, self.model, self.k = embedder, search, llm, model, k
        # Bounds memory in a 384Mi pod and calls against a 30-a-minute provider limit.
        self._slots = threading.BoundedSemaphore(max_concurrent)

    def ask(self, question: str) -> Answer:
        if not self._slots.acquire(blocking=False):
            self._log(question, "unavailable", reason="busy")
            raise Unavailable("busy")
        try:
            return self._ask(question)
        finally:
            self._slots.release()

    def _ask(self, question: str) -> Answer:
        t0 = time.perf_counter()
        hits = list(self.search(self.embedder.embed_query(question), self.k))
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

    def _log(self, question: str, kind: str, *, reason=None, timings=None, tokens=None) -> None:
        log.info(
            "ask q_hash=%s q_len=%d kind=%s reason=%s timings_ms=%s tokens=%s",
            question_hash(question),
            len(question),
            kind,
            reason,
            timings,
            tokens,
        )
