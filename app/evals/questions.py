"""The eval set: questions with their expected sources, loaded from JSONL and validated.

One JSON object per line:

    {"id": "A01", "kind": "answerable", "question": "...",
     "sources": [{"repo": "owner/name", "path": "docs/x.md", "heading": "Triage"}],
     "gist": "what a correct answer says"}
    {"id": "U01", "kind": "unanswerable", "question": "...", "sources": [], "gist": null}

Sources name a document (and optionally a section), never a passage id: ids change whenever the
splitter is tuned, documents and headings do not. `heading` is optional; when given, a passage
counts only if one of its headings starts with it (case ignored).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

KINDS = ("answerable", "unanswerable")


class QuestionError(ValueError):
    """The eval file is wrong; the message says which line and why."""


@dataclass(frozen=True)
class Source:
    repo: str
    path: str
    heading: str | None = None


@dataclass(frozen=True)
class Question:
    id: str
    kind: str
    question: str
    sources: tuple[Source, ...]
    gist: str | None


def _parse(row: dict) -> Question:
    for key in ("id", "kind", "question"):
        if key not in row:
            raise QuestionError(f"missing field {key!r}")
    if row["kind"] not in KINDS:
        raise QuestionError(f"kind must be one of {KINDS}, got {row['kind']!r}")
    if not str(row["question"]).strip():
        raise QuestionError("empty question")
    sources = tuple(
        Source(s["repo"], s["path"], s.get("heading")) for s in row.get("sources") or []
    )
    if row["kind"] == "answerable" and not sources:
        raise QuestionError("an answerable question needs at least one source")
    if row["kind"] == "unanswerable" and sources:
        raise QuestionError("an unanswerable question must not list sources")
    return Question(str(row["id"]), row["kind"], row["question"].strip(), sources, row.get("gist"))


def load_questions(path: Path) -> list[Question]:
    questions: list[Question] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            q = _parse(json.loads(line))
            if q.id in seen:
                raise QuestionError(f"duplicate id {q.id!r}")
        except (json.JSONDecodeError, QuestionError, KeyError, TypeError) as e:
            raise QuestionError(f"{path}: line {number}: {e}") from e
        seen.add(q.id)
        questions.append(q)
    if not questions:
        raise QuestionError(f"{path}: no questions")
    return questions
