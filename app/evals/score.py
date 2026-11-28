"""Score retrieval against the eval set. Pure: the search function is passed in, so this runs
without a database or a model in unit tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.evals.questions import Question, Source
from app.index.store import Hit

Search = Callable[[str], Sequence[Hit]]


def is_hit(hit: Hit, sources: Sequence[Source]) -> bool:
    """A passage is right if it comes from a listed document (and section, when one is listed)."""
    for s in sources:
        if hit.repo != s.repo or hit.path != s.path:
            continue
        if s.heading is None:
            return True
        want = s.heading.lower()
        if any(h.lower().startswith(want) for h in hit.heading_path):
            return True
    return False


@dataclass(frozen=True)
class Result:
    id: str
    kind: str
    question: str
    rank: int | None  # 1-based rank of the first right passage within the top k, else None
    # Similarity and source of the best passage (right or not): the scores of unanswerable
    # questions are what a refusal threshold is chosen from; the path shows what a miss found.
    top_score: float | None
    top_path: str | None

    @property
    def found(self) -> bool:
        return self.rank is not None


@dataclass(frozen=True)
class Report:
    results: tuple[Result, ...]
    k: int
    # Passages added by the same-document rule (ADR 0004), counted after the top k.
    extra: int = 0

    @property
    def answerable(self) -> int:
        return sum(r.kind == "answerable" for r in self.results)

    @property
    def found(self) -> int:
        return sum(r.found for r in self.results if r.kind == "answerable")

    @property
    def recall(self) -> float | None:
        """Share of answerable questions whose right passage is in the top k (None if none)."""
        return self.found / self.answerable if self.answerable else None


def evaluate(
    questions: Sequence[Question], search: Search, *, k: int = 5, extra: int = 0
) -> Report:
    """`search` returns the passages the model would read; at most k + extra of them count."""
    results = []
    for q in questions:
        hits = list(search(q.question))[: k + extra]
        rank = None
        if q.kind == "answerable":
            rank = next((i for i, h in enumerate(hits, 1) if is_hit(h, q.sources)), None)
        top = hits[0] if hits else None
        results.append(
            Result(
                q.id,
                q.kind,
                q.question,
                rank,
                top.score if top else None,
                top.path if top else None,
            )
        )
    return Report(tuple(results), k, extra)
