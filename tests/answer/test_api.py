import threading

import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.answer.llm import Completion, LLMTimeout, RateLimited
from app.answer.service import Answerer
from app.index.store import Hit
from app.main import app

HITS = [
    Hit(
        "a",
        "o/r",
        "docs/a.md",
        ("Runbook", "Restart"),
        "https://x/a#restart",
        "Delete the pod.",
        0.8,
    ),
    Hit("b", "o/r", "docs/b.md", ("Runbook", "Logs"), "https://x/b#logs", "Read the logs.", 0.7),
]


class FakeEmbedder:
    def embed_query(self, text):
        return np.zeros(384, dtype=np.float32)


def answerer(reply=None, error=None, hits=HITS, **kw):
    def llm(messages):
        if error:
            raise error
        return Completion(reply, 120, 15)

    return Answerer(FakeEmbedder(), lambda vec, k: hits, llm, model="m", **kw)


@pytest.fixture
def api():
    yield TestClient(app)
    app.state.answerer = None


def ask(api, question="How do I restart the backend?"):
    return api.post("/ask", json={"question": question})


def test_a_cited_answer_comes_back_with_its_sources(api):
    app.state.answerer = answerer("Delete the pod [1], then read the logs [2].")
    r = ask(api)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "live" and body["answer"].startswith("Delete the pod")
    assert [c["n"] for c in body["citations"]] == [1, 2]
    assert body["citations"][0] == {
        "n": 1,
        "url": "https://x/a#restart",
        "repo": "o/r",
        "path": "docs/a.md",
        "title": "Runbook > Restart",
    }
    assert body["tokens"] == {"prompt": 120, "completion": 15}
    assert set(body["timings_ms"]) == {"retrieve", "generate"}


def test_only_the_cited_passages_are_returned(api):
    app.state.answerer = answerer("Read the logs [2].")
    assert [c["path"] for c in ask(api).json()["citations"]] == ["docs/b.md"]


def test_a_refusal_is_a_normal_200_without_citations(api):
    app.state.answerer = answerer("I don't know.")
    body = ask(api).json()
    assert body["kind"] == "refusal" and body["citations"] == [] and body["reason"] == "model"


def test_an_uncited_answer_is_refused(api):
    app.state.answerer = answerer("Just reboot the node.")
    body = ask(api).json()
    assert body["kind"] == "refusal" and body["reason"] == "uncited"


@pytest.mark.parametrize(
    "error, reason", [(RateLimited("429"), "rate_limited"), (LLMTimeout("slow"), "timeout")]
)
def test_provider_trouble_is_a_503_with_a_notice(api, error, reason):
    app.state.answerer = answerer(error=error)
    r = ask(api)
    assert r.status_code == 503
    assert r.json()["kind"] == "unavailable" and r.json()["reason"] == reason
    assert "notice" in r.json()


@pytest.mark.parametrize(
    "error",
    [
        # Before the first index run:
        psycopg.errors.UndefinedTable('relation "passages" does not exist'),
        psycopg.OperationalError("connection refused"),  # a Postgres outage
    ],
    ids=["missing_table", "connection_error"],
)
def test_a_database_error_is_a_503_not_a_500(api, error, caplog):
    def broken_search(vec, k):
        raise error

    called = []
    a = Answerer(FakeEmbedder(), broken_search, lambda m: called.append(1), model="m")
    app.state.answerer = a
    with caplog.at_level("INFO"):
        r = ask(api, "my very secret question about the database")
    assert r.status_code == 503
    body = r.json()
    assert body["kind"] == "unavailable" and body["reason"] == "index_unavailable"
    assert body["notice"] and called == []  # no model call without passages
    # One log line, no traceback, and never the question itself.
    assert "reason=index_unavailable" in caplog.text
    assert "Traceback" not in caplog.text and "secret question" not in caplog.text
    # The slot was released: the next request is not turned away as "busy".
    assert ask(api).json()["reason"] == "index_unavailable"


def test_no_passages_means_a_refusal_without_calling_the_model(api):
    called = []
    a = answerer("should not be used", hits=[])
    a.llm = lambda messages: called.append(1)
    app.state.answerer = a
    body = ask(api).json()
    assert body["kind"] == "refusal" and called == []


def test_a_third_concurrent_request_is_turned_away_at_once(api):
    entered, release = threading.Event(), threading.Event()

    def slow_llm(messages):
        entered.set()
        release.wait(5)
        return Completion("Done [1].", 1, 1)

    a = Answerer(FakeEmbedder(), lambda vec, k: HITS, slow_llm, model="m", max_concurrent=1)
    app.state.answerer = a
    t = threading.Thread(target=lambda: ask(api))
    t.start()
    entered.wait(5)
    try:
        r = ask(api)
        assert r.status_code == 503 and r.json()["reason"] == "busy"
    finally:
        release.set()
        t.join()


@pytest.mark.parametrize("question", ["", "hi", "x" * 501])
def test_questions_that_are_too_short_or_too_long_are_rejected(api, question):
    app.state.answerer = answerer("x [1]")
    assert ask(api, question).status_code == 422


def test_without_configuration_ask_says_so(api):
    app.state.answerer = None
    r = ask(api)
    assert r.status_code == 503 and r.json()["reason"] == "not_configured"


def test_the_question_text_never_reaches_the_logs(api, caplog):
    app.state.answerer = answerer("Delete the pod [1].")
    with caplog.at_level("INFO"):
        ask(api, "my very secret question about the database")
    assert "secret question" not in caplog.text
    assert "q_hash=" in caplog.text


def test_healthz_still_works_without_any_configuration(api):
    app.state.answerer = None
    assert api.get("/healthz").json() == {"status": "ok"}
