"""Score retrieval against the eval set, using the real index and model (no LLM calls, no cost).

    python -m app.evals.retrieval                       # report only
    python -m app.evals.retrieval --min-recall 0.9      # exit 1 below the target (the M2 CI gate)

Needs the index (python -m app.index) and the model (python -m app.embed.download).
Exit codes: 0 ok, 1 below --min-recall, 2 a problem with the file, the model or the database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from app.embed.model import DEFAULT_DIR, OnnxEmbedder
from app.evals.questions import QuestionError, load_questions
from app.evals.score import Report, evaluate
from app.index.store import connect, search


def _score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"  # None: the index returned nothing


def render(report: Report) -> str:
    lines = []
    for r in report.results:
        if r.kind == "answerable":
            mark = f"found at rank {r.rank}" if r.found else f"MISSED (best: {r.top_path})"
            lines.append(f"  {r.id:5} {mark}  [score {_score(r.top_score)}]  {r.question[:70]}")
        else:
            lines.append(
                f"  {r.id:5} unanswerable, best score {_score(r.top_score)} ({r.top_path})"
            )
    answerable = [r.top_score for r in report.results if r.kind == "answerable"]
    unanswerable = [r.top_score for r in report.results if r.kind == "unanswerable"]
    lines.append("")
    if report.recall is not None:
        lines.append(
            f"right passage in the top {report.k}: {report.found}/{report.answerable} "
            f"= {report.recall:.0%}"
        )
        lowest = min((s for s in answerable if s is not None), default=None)
        lines.append(f"  best-passage score on answerable questions: lowest {_score(lowest)}")
    if unanswerable:
        scores = [s for s in unanswerable if s is not None]
        lines.append(
            f"unanswerable: {len(unanswerable)} questions, best-passage scores"
            f" {_score(min(scores, default=None))} to {_score(max(scores, default=None))}"
            " (a refusal threshold has to sit between this range and the answerable one)"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evals.retrieval")
    ap.add_argument("--file", type=Path, default=Path("evals/questions.jsonl"))
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--min-recall", type=float, help="exit 1 if recall is below this (0 to 1)")
    ap.add_argument("--model-dir", type=Path, default=DEFAULT_DIR)
    args = ap.parse_args(argv)
    try:
        questions = load_questions(args.file)
        embedder = OnnxEmbedder(args.model_dir)
        with connect() as conn:
            report = evaluate(
                questions, lambda q: search(conn, embedder.embed_query(q), k=args.k), k=args.k
            )
    except (QuestionError, FileNotFoundError, psycopg.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(render(report))
    if args.min_recall is not None and (report.recall or 0.0) < args.min_recall:
        print(f"below the target of {args.min_recall:.0%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
