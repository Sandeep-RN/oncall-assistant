import json

import pytest

from app.evals.questions import Question, QuestionError, Source, load_questions
from app.evals.score import evaluate, is_hit
from app.index.store import Hit

REPO = "o/r"


def hit(path, heading=("T", "Sec"), score=0.8, repo=REPO):
    return Hit("id", repo, path, tuple(heading), "https://x", "text", score)


def write(tmp_path, rows):
    p = tmp_path / "q.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def answerable(qid="A01", path="docs/a.md", heading=None):
    return {
        "id": qid,
        "kind": "answerable",
        "question": "q?",
        "gist": "g",
        "sources": [{"repo": REPO, "path": path, **({"heading": heading} if heading else {})}],
    }


def unanswerable(qid="U01"):
    return {"id": qid, "kind": "unanswerable", "question": "q?", "gist": None, "sources": []}


# --- loading and validation -------------------------------------------------------------------


def test_loads_both_kinds(tmp_path):
    qs = load_questions(write(tmp_path, [answerable(), unanswerable()]))
    assert [q.kind for q in qs] == ["answerable", "unanswerable"]
    assert qs[0].sources == (Source(REPO, "docs/a.md", None),)


@pytest.mark.parametrize(
    "row, message",
    [
        ({**answerable(), "sources": []}, "needs at least one source"),
        ({**unanswerable(), "sources": answerable()["sources"]}, "must not list sources"),
        ({**answerable(), "kind": "maybe"}, "kind"),
        ({**answerable(), "question": "  "}, "empty question"),
        ({k: v for k, v in answerable().items() if k != "id"}, "id"),
    ],
)
def test_invalid_rows_are_refused_with_the_line_number(tmp_path, row, message):
    with pytest.raises(QuestionError, match=message) as e:
        load_questions(write(tmp_path, [row]))
    assert "line 1" in str(e.value)


def test_duplicate_ids_are_refused(tmp_path):
    with pytest.raises(QuestionError, match="duplicate id"):
        load_questions(write(tmp_path, [answerable("A01"), answerable("A01")]))


def test_bad_json_and_empty_file_are_refused(tmp_path):
    p = tmp_path / "q.jsonl"
    p.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(QuestionError, match="line 1"):
        load_questions(p)
    p.write_text("\n", encoding="utf-8")
    with pytest.raises(QuestionError, match="no questions"):
        load_questions(p)


# --- what counts as a right passage -----------------------------------------------------------


def test_a_hit_needs_the_same_repo_and_path():
    s = (Source(REPO, "docs/a.md", None),)
    assert is_hit(hit("docs/a.md"), s)
    assert not is_hit(hit("docs/b.md"), s)
    assert not is_hit(hit("docs/a.md", repo="o/other"), s)


def test_a_heading_must_match_a_section_in_the_passages_path_ignoring_case_and_suffix():
    s = (Source(REPO, "docs/a.md", "triage"),)
    assert is_hit(hit("docs/a.md", ("Runbook", "Triage (5 minutes)")), s)
    assert not is_hit(hit("docs/a.md", ("Runbook", "Database (503)")), s)


def test_any_listed_source_is_enough():
    s = (Source(REPO, "docs/a.md", None), Source(REPO, "docs/b.md", None))
    assert is_hit(hit("docs/b.md"), s)


# --- scoring ----------------------------------------------------------------------------------


def qs(*rows):
    return [
        Question(
            r["id"], r["kind"], r["question"], tuple(Source(**s) for s in r["sources"]), r["gist"]
        )
        for r in rows
    ]


def test_recall_counts_only_answerable_questions_and_records_the_rank():
    questions = qs(
        answerable("A01", "docs/a.md"), answerable("A02", "docs/b.md"), unanswerable("U01")
    )
    results_by_q = {
        "q?": [hit("docs/x.md", score=0.9), hit("docs/a.md", score=0.8)],
    }
    report = evaluate(questions, lambda q: results_by_q["q?"], k=5)
    assert report.answerable == 2 and report.found == 1  # A01 found at rank 2, A02 not
    assert report.recall == pytest.approx(0.5)
    a01 = next(r for r in report.results if r.id == "A01")
    assert a01.rank == 2 and not next(r for r in report.results if r.id == "A02").found


def test_only_the_top_k_count():
    questions = qs(answerable("A01", "docs/a.md"))
    hits = [hit("docs/x.md")] * 5 + [hit("docs/a.md")]
    assert evaluate(questions, lambda q: hits, k=5).found == 0
    assert evaluate(questions, lambda q: hits, k=6).found == 1


def test_unanswerable_questions_report_the_best_score_and_are_not_scored():
    questions = qs(unanswerable("U01"), unanswerable("U02"))
    report = evaluate(
        questions, lambda q: [hit("docs/x.md", score=0.61), hit("docs/y.md", score=0.5)], k=5
    )
    assert report.answerable == 0 and report.recall is None
    assert [r.top_score for r in report.results] == [0.61, 0.61]


def test_an_empty_index_gives_no_hits_not_a_crash():
    report = evaluate(qs(answerable("A01")), lambda q: [], k=5)
    assert report.found == 0 and report.results[0].top_score is None


def test_the_report_renders_even_when_the_index_is_empty():
    from app.evals.retrieval import render

    report = evaluate(qs(answerable("A01"), unanswerable("U01")), lambda q: [], k=5)
    text = render(report)
    assert "0/1" in text and "n/a" in text


def test_the_report_names_what_a_missed_question_found_instead():
    from app.evals.retrieval import render

    questions = qs(answerable("A01", "docs/a.md"))
    text = render(evaluate(questions, lambda q: [hit("docs/other.md", score=0.71)], k=5))
    assert "MISSED (best: docs/other.md)" in text and "0%" in text
