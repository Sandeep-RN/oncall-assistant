"""Saved answers (issue #6, ADR 0003): loading, exact matching, the shipped file, and the build."""

import json
import re
from pathlib import Path

import pytest

from app.answer.service import Answer
from app.evals.questions import load_questions
from app.saved.build import SAVED_QUESTIONS, BuildError, build_saved
from app.saved.store import SAVED_FILE, SavedAnswers, load_saved, normalize

ROOT = Path(__file__).parents[2]
LOCK = json.loads((ROOT / "corpus-lock.json").read_text())

URL = "https://github.com/Sandeep-RN/r/blob/abc/docs/a.md#restart"


def citation(n=1, url=URL):
    return {"n": n, "url": url, "repo": "Sandeep-RN/r", "path": "docs/a.md", "title": "Runbook"}


def entry(id="restart", question="How do I restart the backend?", answer=None, citations=None):
    return {
        "id": id,
        "question": question,
        "answer": "Delete the pod [1]." if answer is None else answer,
        "citations": [citation()] if citations is None else citations,
    }


def write(tmp_path, answers, **extra):
    path = tmp_path / "answers.json"
    path.write_text(json.dumps({"answers": answers, **extra}))
    return path


# --- matching: exact after normalising, never similarity (ADR 0003, point 3) -------------------


@pytest.mark.parametrize(
    "a, b",
    [
        ("How do I roll back?", "  how do i ROLL back "),
        ("How do I roll back?", "how do i roll back"),
        ("Errors started right after a deploy.", "errors started right after a deploy"),
        ("Rolling   back\ta\ndeploy?!", "rolling back a deploy"),
    ],
)
def test_normalising_ignores_case_spacing_and_punctuation(a, b):
    assert normalize(a) == normalize(b)


def test_a_different_question_does_not_normalise_to_the_same_text():
    assert normalize("How do I roll back?") != normalize("How do I roll forward?")


def test_a_question_matches_only_its_own_saved_answer(tmp_path):
    saved = load_saved(write(tmp_path, [entry(), entry("other", "What is the memory cap?")]))
    assert saved.match("  HOW do I restart the backend ") == "restart"
    assert saved.match("What is the memory cap") == "other"
    assert saved.match("How do I restart the frontend?") is None  # near, but not equal
    assert saved.match("") is None and saved.match("???") is None


def test_the_list_carries_everything_the_page_shows(tmp_path):
    saved = load_saved(write(tmp_path, [entry()]))
    assert saved.all() == [entry()]


# --- loading: a bad file fails at startup, never on a visitor ---------------------------------


@pytest.mark.parametrize(
    "answers, why",
    [
        ([], "no answers"),
        ([entry(), entry()], "duplicate id"),
        ([entry(citations=[])], "no citation"),
        ([entry(answer="Delete the pod [2].")], "marker beyond the citations"),
        ([entry(answer="Delete the pod.")], "no marker at all"),
        ([entry(citations=[citation(url="https://evil.example/x")])], "not a platform repo"),
        ([entry(answer="  ")], "empty answer"),
        ([entry(question="x")], "question the API would reject"),
        ([entry(id="Not A Slug")], "id is not a slug"),
        ([{"id": "a", "question": "How do I restart the backend?"}], "missing keys"),
    ],
)
def test_a_bad_file_is_refused(tmp_path, answers, why):
    with pytest.raises(ValueError):
        load_saved(write(tmp_path, answers))


def test_a_file_that_is_not_json_is_refused(tmp_path):
    path = tmp_path / "answers.json"
    path.write_text("{not json")
    with pytest.raises(ValueError):
        load_saved(path)


# --- the file that ships in the image ---------------------------------------------------------


@pytest.fixture(scope="module")
def shipped():
    return load_saved(SAVED_FILE)


def test_five_saved_answers_ship(shipped):
    assert len(shipped.all()) == 5
    assert [a["id"] for a in shipped.all()] == list(SAVED_QUESTIONS)


def test_each_saved_question_matches_itself_and_is_an_answerable_eval_question(shipped):
    # Tying the saved questions to the eval set means the retrieval eval already covers them.
    answerable = {normalize(q.question): q for q in load_questions(ROOT / "evals/questions.jsonl")}
    for a in shipped.all():
        assert shipped.match(a["question"]) == a["id"]
        q = answerable.get(normalize(a["question"]))
        assert q is not None and q.kind == "answerable", a["id"]


def test_every_saved_citation_is_pinned_to_the_current_corpus(shipped):
    # CI cannot fetch the corpus, but it can tell that a saved answer was built at an older pin.
    # Moving the pin in corpus-lock.json must force a rebuild and a new review.
    for a in shipped.all():
        for c in a["citations"]:
            prefix = f"https://github.com/{c['repo']}/blob/{LOCK[c['repo']]}/{c['path']}#"
            assert c["url"].startswith(prefix), f"{a['id']} [{c['n']}] is not at the pinned commit"


def test_saved_ids_are_plain_slugs(shipped):
    assert all(re.fullmatch(r"[a-z0-9-]+", a["id"]) for a in shipped.all())


# --- decisions from the second-model review of 2026-11-23 (each answer read beside its passages) --


def answer_text(shipped, id_):
    return next(a for a in shipped.all() if a["id"] == id_)["answer"]


def test_the_revoke_answer_keeps_the_runbooks_not_run_on_k3s_caveat(shipped):
    # The runbook it cites still says "Not run on k3s yet" (checked 2026-11-23). A saved answer is
    # shown as fact, so it must not present an untested procedure as proven.
    assert "not been run on k3s" in answer_text(shipped, "revoke-a-token")


def test_the_revoke_answer_keeps_the_checks_and_the_leaked_links_warning(shipped):
    text = answer_text(shipped, "revoke-a-token")
    assert "${#TOKEN}" in text  # without it a 401 does not prove the token was revoked
    assert "keep working" in text  # links the leaked token already made


def test_answers_taken_from_link_shortener_runbooks_say_which_system_they_are_about(shipped):
    # The assistant's own database has no backups and its deploys are not the link shortener's.
    for id_ in ("roll-back-a-deploy", "no-point-in-time-restore"):
        assert "link shortener" in answer_text(shipped, id_).lower(), id_


def test_the_availability_answer_does_not_claim_a_ranking_its_source_does_not_make(shipped):
    # The roadmap lists its accepted limits in a table and does not rank them.
    text = answer_text(shipped, "biggest-availability-limit")
    assert "does not rank" in text
    assert "biggest availability limit is" not in text.lower()


def test_no_answer_uses_a_word_the_review_found_unsupported(shipped):
    # "immediately" (roll back) and "simply" (revoke) are in no source passage.
    for a in shipped.all():
        assert "immediately" not in a["answer"].lower(), a["id"]
        assert "simply" not in a["answer"].lower(), a["id"]


# --- the build: only a real, cited, live answer may become a saved answer ----------------------


def live(text="Delete the pod [1].", cites=(1,)):
    return Answer("live", text, [citation(n) for n in cites], model="m")


QUESTIONS = {"restart": "How do I restart the backend?", "memory-cap": "What is the memory cap?"}


def test_the_build_writes_the_answers_in_order_and_the_result_loads(tmp_path):
    path = tmp_path / "out.json"
    n = build_saved(lambda q: live(), QUESTIONS, generated="2026-11-22", path=path)
    assert n == 2
    saved = load_saved(path)
    assert [a["id"] for a in saved.all()] == ["restart", "memory-cap"]
    assert json.loads(path.read_text())["generated"] == "2026-11-22"


@pytest.mark.parametrize(
    "result",
    [Answer("refusal", "I don't know.", reason="model"), live(cites=())],
    ids=["refusal", "live answer without a citation"],
)
def test_the_build_refuses_anything_but_a_cited_live_answer(tmp_path, result):
    path = tmp_path / "out.json"
    with pytest.raises(BuildError, match="restart"):
        build_saved(lambda q: result, QUESTIONS, generated="2026-11-22", path=path)
    assert not path.exists()  # nothing half-written: the old file, if any, is untouched


def test_the_build_leaves_the_old_file_alone_when_a_question_fails(tmp_path):
    path = tmp_path / "out.json"
    path.write_text("old contents")
    answers = iter([live(), Answer("refusal", "I don't know.", reason="model")])
    with pytest.raises(BuildError):
        build_saved(lambda q: next(answers), QUESTIONS, generated="2026-11-22", path=path)
    assert path.read_text() == "old contents"


def test_the_build_replaces_lookalike_characters_a_copy_paste_would_break_on(tmp_path):
    # Found 2026-11-22: gpt-oss wrote a file path with U+2011 non-breaking hyphens
    # (`link‑tokens‑sealedsecret.yaml`), which does not exist when pasted into a shell.
    text = "Edit `link‑tokens.yaml`, revert the tag‑bump’s PR now [1]."
    path = tmp_path / "out.json"
    build_saved(lambda q: live(text), {"restart": "How do I restart?"}, generated="d", path=path)
    assert (
        load_saved(path).all()[0]["answer"]
        == "Edit `link-tokens.yaml`, revert the tag-bump's PR now [1]."
    )


def test_the_shipped_answers_hold_no_lookalike_characters(shipped):
    bad = "‐‑  ‘’“”"
    for a in shipped.all():
        assert not [ch for ch in a["answer"] if ch in bad], a["id"]


def test_every_question_the_build_asks_exists_in_the_eval_set():
    ids = {q.id for q in load_questions(ROOT / "evals/questions.jsonl")}
    assert set(SAVED_QUESTIONS.values()) <= ids


def test_saved_answers_type_is_what_the_service_expects():
    assert isinstance(load_saved(SAVED_FILE), SavedAnswers)
