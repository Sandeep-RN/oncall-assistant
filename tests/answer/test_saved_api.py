"""POST /ask degrades to saved answers on capacity limits, and only on those (ADR 0003).

Capacity (the free tier doing what it was always going to do) answers 200 `saved`, which counts as
a good response. Faults stay 503, so the availability target can still burn on a real failure.
"""

import threading

import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.answer.llm import BadResponse, Completion, LLMTimeout, ProviderError, RateLimited
from app.answer.service import Answerer
from app.index.store import Hit
from app.main import SAVED, app
from app.saved.store import SavedAnswers

CITE = {"n": 1, "url": "https://github.com/Sandeep-RN/r/blob/abc/docs/a.md#x", "repo": "x/r"}
CITE["path"], CITE["title"] = "docs/a.md", "Runbook"
ITEMS = [
    {"id": "restart", "question": "How do I restart the backend?", "answer": "Delete [1].",
     "citations": [CITE]},
    {"id": "cap", "question": "What is the memory cap?", "answer": "One GiB [1].",
     "citations": [CITE]},
]  # fmt: skip
HITS = [Hit("a", "o/r", "docs/a.md", ("Runbook",), "https://x/a", "Delete the pod.", 0.8)]


class FakeEmbedder:
    def embed_query(self, text):
        return np.zeros(384, dtype=np.float32)


SAVED_FOR_TESTS = SavedAnswers(ITEMS)


def answerer(error=None, saved=SAVED_FOR_TESTS, search=None, **kw):
    def llm(messages):
        if error:
            raise error
        return Completion("Delete the pod [1].", 10, 5)

    return Answerer(
        FakeEmbedder(), search or (lambda v, k: HITS), llm, model="m", saved=saved, **kw
    )


@pytest.fixture
def api():
    yield TestClient(app)
    app.state.answerer = None


def ask(api, question="How do I restart the frontend?"):
    return api.post("/ask", json={"question": question})


def test_a_provider_429_answers_200_with_the_saved_answers(api):
    app.state.answerer = answerer(RateLimited("429"))
    r = ask(api)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "saved" and body["reason"] == "rate_limited"
    assert body["notice"] and "saved" in body["notice"].lower()
    assert body["match"] is None  # the question is not one of the saved ones
    assert body["saved"] == ITEMS


def test_a_question_equal_to_a_saved_one_says_which(api):
    app.state.answerer = answerer(RateLimited("429"))
    body = ask(api, "  how do I RESTART the backend  ").json()
    assert body["kind"] == "saved" and body["match"] == "restart"


def test_two_answers_already_running_answers_200_saved_not_503(api):
    entered, release = threading.Event(), threading.Event()

    def slow_llm(messages):
        entered.set()
        release.wait(5)
        return Completion("Done [1].", 1, 1)

    a = Answerer(FakeEmbedder(), lambda v, k: HITS, slow_llm, model="m", max_concurrent=1,
                 saved=SavedAnswers(ITEMS))  # fmt: skip
    app.state.answerer = a
    t = threading.Thread(target=lambda: ask(api))
    t.start()
    entered.wait(5)
    try:
        r = ask(api)
        assert r.status_code == 200
        assert r.json()["kind"] == "saved" and r.json()["reason"] == "busy"
    finally:
        release.set()
        t.join()


@pytest.mark.parametrize(
    "error, reason",
    [
        (LLMTimeout("slow"), "timeout"),
        (ProviderError("HTTP 500"), "provider_error"),
        (BadResponse("empty"), "bad_response"),
    ],
)
def test_faults_stay_503_even_with_saved_answers_configured(api, error, reason):
    app.state.answerer = answerer(error)
    r = ask(api)
    assert r.status_code == 503
    assert r.json()["kind"] == "unavailable" and r.json()["reason"] == reason


def test_a_database_fault_stays_503_with_saved_answers_configured(api):
    def broken(vec, k):
        raise psycopg.OperationalError("connection refused")

    app.state.answerer = answerer(search=broken)
    r = ask(api)
    assert r.status_code == 503 and r.json()["reason"] == "index_unavailable"


def test_without_saved_answers_a_429_is_still_the_old_503(api):
    app.state.answerer = answerer(RateLimited("429"), saved=None)
    r = ask(api)
    assert r.status_code == 503 and r.json()["reason"] == "rate_limited"


def test_a_saved_reply_is_logged_as_saved_without_the_question(api, caplog):
    app.state.answerer = answerer(RateLimited("429"))
    with caplog.at_level("INFO"):
        ask(api, "my very secret question about the database")
    assert "kind=saved" in caplog.text and "reason=rate_limited" in caplog.text
    assert "secret question" not in caplog.text


def test_the_slot_is_released_after_a_saved_reply(api):
    app.state.answerer = answerer(RateLimited("429"), max_concurrent=1)
    for _ in range(2):  # a leaked slot would turn the second one into "busy"
        assert ask(api).json()["reason"] == "rate_limited"


def test_get_saved_is_a_503_when_the_file_could_not_be_loaded(api, monkeypatch):
    monkeypatch.setattr("app.main.SAVED", None)
    r = api.get("/saved")
    assert r.status_code == 503 and r.json()["reason"] == "not_configured"


def test_a_broken_saved_file_switches_the_feature_off_instead_of_stopping_the_app(
    monkeypatch, caplog
):
    # The build script that regenerates the file imports app.main: a hard failure here would make
    # a broken file impossible to rebuild.
    from app.main import _load_saved

    def broken():
        raise ValueError("a citation needs the keys")

    monkeypatch.setattr("app.main.load_saved", broken)
    assert _load_saved() is None
    assert "saved answers not available" in caplog.text


def test_get_saved_lists_the_shipped_answers_without_any_configuration(api):
    app.state.answerer = None
    r = api.get("/saved")
    assert r.status_code == 200
    body = r.json()["saved"]
    assert len(body) == 5 == len(SAVED.all())
    assert {"id", "question", "answer", "citations"} <= set(body[0])
