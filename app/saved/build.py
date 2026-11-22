"""Build app/saved/answers.json by asking the real pipeline (ADR 0003).

    python -m app.saved.build                       # Groq key from the environment
    LLM_PROVIDER=kodekey python -m app.saved.build  # the development key, laptop only

Needs the model files, an index (PG* or DATABASE_URL) built from the pinned corpus, and a provider
key. Each question comes from the eval set by id, so the retrieval eval already covers it. An
answer becomes a saved answer only if it is a LIVE answer with at least one citation: a refusal, an
uncited answer, a provider error or a saved reply stops the build, and the existing file is left
untouched. The output is a DRAFT: a model wrote it and a person approves it in the pull request,
reading each answer beside the passages it cites. The citation check proves a citation exists, not
that it supports the claim (ADR 0002), and on 2026-11-22 two of the five drafts added a sentence
their passage does not make. Trim such sentences by hand and say so in the file's "note"; a
rebuild overwrites the file, so re-review the diff.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path

from app.answer.service import Answer
from app.saved.store import SAVED_FILE, load_saved

# slug -> id of the question in evals/questions.jsonl. Chosen from answerable questions whose right
# passage the retrieval eval finds (not A01, A05 or A08, which it misses), and whose answers do not
# change week to week.
SAVED_QUESTIONS = {
    "roll-back-a-deploy": "A03",
    "revoke-a-token": "A10",
    "no-point-in-time-restore": "A16",
    "biggest-availability-limit": "A20",
    "assistant-memory-cap": "A27",
}


# Characters a model writes that LOOK like ASCII but break a copy-paste into a shell or a search.
# Found 2026-11-22: gpt-oss-120b wrote a file path with U+2011 non-breaking hyphens.
LOOKALIKES = str.maketrans(
    {
        "‐": "-",  # hyphen
        "‑": "-",  # non-breaking hyphen
        " ": " ",  # no-break space
        " ": " ",  # narrow no-break space
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
    }
)


class BuildError(RuntimeError):
    """A question did not give a cited live answer, or the result would not load."""


def build_saved(
    ask: Callable[[str], Answer],
    questions: Mapping[str, str],
    *,
    generated: str,
    path: Path = SAVED_FILE,
) -> int:
    answers = []
    model = ""
    for slug, question in questions.items():
        result = ask(question)
        # Checked in this order on purpose: a saved reply has no `citations` attribute.
        if result.kind != "live" or not result.citations:
            raise BuildError(
                f"{slug}: expected a cited live answer, got {result.kind}"
                f" ({getattr(result, 'reason', None)})"
            )
        model = result.model
        answers.append(
            {
                "id": slug,
                "question": question,
                "answer": result.answer.translate(LOOKALIKES),
                "citations": result.citations,
            }
        )
    # Written next to the target and renamed, so a crash never leaves half a file, and the
    # result is loaded with the same checks the app runs at startup before it replaces anything.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(
            {"generated": generated, "model": model, "answers": answers},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        load_saved(tmp)
    except ValueError as e:
        tmp.unlink(missing_ok=True)
        raise BuildError(f"the built file is not valid: {e}") from e
    os.replace(tmp, path)
    return len(answers)


def main() -> int:
    from app.evals.questions import load_questions
    from app.main import build_answerer

    eval_file = Path(__file__).parents[2] / "evals" / "questions.jsonl"
    by_id = {q.id: q.question for q in load_questions(eval_file)}
    questions = {slug: by_id[qid] for slug, qid in SAVED_QUESTIONS.items()}
    answerer, (pool, http) = build_answerer()
    try:
        n = build_saved(answerer.ask, questions, generated=date.today().isoformat())
    except BuildError as e:
        print(f"build failed: {e}", file=sys.stderr)
        return 1
    finally:
        pool.close()
        http.close()
    print(f"wrote {n} saved answers to {SAVED_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
