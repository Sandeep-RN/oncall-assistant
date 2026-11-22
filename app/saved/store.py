"""Saved answers: a handful of pre-written, cited answers shown when the free model tier is at its
limit (ADR 0003). They live in the image (answers.json), not in the database, so they work while
Postgres is down.

The file is validated when the app starts, so a broken file fails the pod at startup and the CI
smoke test, never a visitor. Matching a visitor's question to a saved one is EXACT after
normalising: similarity scores cannot be trusted to say a question is "the same" (ADR 0002), and a
wrong saved answer shown with confidence is worse than none.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SAVED_FILE = Path(__file__).parent / "answers.json"

# Citations may link only to this account's repos, the same rule the page applies (app/page.py).
REPO_PREFIX = "https://github.com/Sandeep-RN/"
MARKER = re.compile(r"\[(\d+)\]")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
REQUIRED = ("id", "question", "answer", "citations")
CITATION_KEYS = ("n", "url", "repo", "path", "title")


def normalize(question: str) -> str:
    """Lowercase, punctuation to spaces, spaces collapsed: "Roll-back?" matches "roll back"."""
    return " ".join(re.sub(r"[^\w\s]", " ", question.casefold()).split())


class SavedAnswers:
    def __init__(self, items: list[dict]):
        self._items = items
        self._by_question = {normalize(i["question"]): i["id"] for i in items}

    def all(self) -> list[dict]:
        return [dict(i) for i in self._items]

    def match(self, question: str) -> str | None:
        """The id of the saved answer whose question equals this one (normalised), else None."""
        key = normalize(question)
        return self._by_question.get(key) if key else None


def _check(item: object, seen_ids: set[str], seen_questions: set[str]) -> dict:
    if not isinstance(item, dict) or any(k not in item for k in REQUIRED):
        raise ValueError(f"every saved answer needs {REQUIRED}")
    id_, question, answer, citations = (item[k] for k in REQUIRED)
    if not isinstance(id_, str) or not SLUG.fullmatch(id_):
        raise ValueError(f"id {id_!r} is not a lowercase slug")
    if id_ in seen_ids:
        raise ValueError(f"duplicate id {id_!r}")
    # The same limits the API puts on a question, so a saved question could be typed in.
    if not isinstance(question, str) or not 3 <= len(question.strip()) <= 500:
        raise ValueError(f"{id_}: the question must be 3 to 500 characters")
    key = normalize(question)
    if key in seen_questions:
        raise ValueError(f"{id_}: another saved answer has the same question")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError(f"{id_}: empty answer")
    if not isinstance(citations, list) or not citations:
        raise ValueError(f"{id_}: a saved answer needs at least one citation")
    numbers = set()
    for c in citations:
        if not isinstance(c, dict) or any(k not in c for k in CITATION_KEYS):
            raise ValueError(f"{id_}: a citation needs {CITATION_KEYS}")
        if not isinstance(c["n"], int) or c["n"] in numbers:
            raise ValueError(f"{id_}: citation numbers must be unique integers")
        if not str(c["url"]).startswith(REPO_PREFIX):
            raise ValueError(f"{id_}: citation {c['n']} does not link to a platform repo")
        numbers.add(c["n"])
    markers = {int(m) for m in MARKER.findall(answer)}
    if not markers or not markers <= numbers:
        raise ValueError(f"{id_}: the answer's [n] markers must point at its citations")
    seen_ids.add(id_)
    seen_questions.add(key)
    return item


def load_saved(path: Path = SAVED_FILE) -> SavedAnswers:
    """Read and validate the saved answers; ValueError says what is wrong."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path}: no saved answers")
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    return SavedAnswers([_check(i, seen_ids, seen_questions) for i in items])
