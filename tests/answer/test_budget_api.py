"""POST /ask with the daily budget and demo tokens (ADR 0003).

A spent budget is a CAPACITY limit: 200 with saved answers, and no embedding and no model call (it
costs nothing). A token holder may use what the public cannot. A wrong token is a 401, never a
silent downgrade to the public budget. A broken LEDGER must not stop answering (fail open); a
database that is DOWN must fail at once, not after a second pool wait.
"""

import hashlib
from datetime import date

import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.answer.llm import Completion, RateLimited
from app.answer.service import ESTIMATED_TOKENS, Answerer
from app.budget.budget import PUBLIC, Budget, BudgetSettings
from app.budget.tokens import DemoTokens
from app.index.store import Hit
from app.main import app
from app.saved.store import SavedAnswers

DAY = date(2026, 11, 23)
TOKEN = "t" * 64
HITS = [Hit("a", "o/r", "docs/a.md", ("Runbook", "Restart"), "https://x/a", "Delete the pod.", 0.8)]
CITE = {"n": 1, "url": "https://github.com/Sandeep-RN/r/blob/abc/d.md#x", "repo": "x/r"}
CITE["path"], CITE["title"] = "d.md", "D"
ITEMS = [
    {"id": "restart", "question": "How do I restart the backend?", "answer": "Delete [1].",
     "citations": [CITE]},
]  # fmt: skip


class FakeLedger:
    def __init__(self):
        self.rows = {}
        self.fail_used = None
        self.fail_add = None

    def used(self, day):
        if self.fail_used:
            raise self.fail_used
        return {w: t for (d, w), t in self.rows.items() if d == day}

    def add(self, day, who, tokens):
        if self.fail_add:
            raise self.fail_add
        self.rows[(day, who)] = self.rows.get((day, who), 0) + tokens


class Counting:
    """Counts what the pipeline was asked to do, so 'costs nothing' can be asserted."""

    def __init__(self, completion=None, error=None):
        self.embeds = self.searches = self.model_calls = 0
        self.completion = completion or Completion("Delete the pod [1].", 1500, 300)
        self.error = error

    def embedder(self):
        outer = self

        class E:
            def embed_query(self, text):
                outer.embeds += 1
                return np.zeros(384, dtype=np.float32)

        return E()

    def search(self, vec, k):
        self.searches += 1
        return HITS

    def llm(self, messages):
        self.model_calls += 1
        if self.error:
            raise self.error
        return self.completion


@pytest.fixture
def ledger():
    return FakeLedger()


@pytest.fixture
def api(tmp_path, monkeypatch):
    (tmp_path / "owner").write_text(hashlib.sha256(TOKEN.encode()).hexdigest())
    monkeypatch.setattr("app.main.TOKENS", DemoTokens(tmp_path))
    yield TestClient(app)
    app.state.answerer = None


def install(ledger, counting=None, total=1000, pct=70, **kw):
    c = counting or Counting()
    budget = Budget(ledger, BudgetSettings(total, pct), today=lambda: DAY)
    app.state.answerer = Answerer(
        c.embedder(), c.search, c.llm, model="m", saved=SavedAnswers(ITEMS), budget=budget, **kw
    )
    return c


def ask(api, question="How do I restart the frontend?", token=None):
    headers = {} if token is None else {"X-Demo-Token": token}
    return api.post("/ask", json={"question": question}, headers=headers)


# --- counting -----------------------------------------------------------------------------------


def test_a_live_answer_is_counted_in_tokens_under_public(api, ledger):
    install(ledger)
    r = ask(api)
    assert r.status_code == 200 and r.json()["kind"] == "live"
    assert ledger.rows == {(DAY, PUBLIC): 1800}  # 1500 prompt + 300 completion


def test_a_reply_without_usage_counts_an_estimate(api, ledger):
    install(ledger, Counting(Completion("Delete the pod [1].", 0, 0)))
    ask(api)
    assert ledger.rows == {(DAY, PUBLIC): ESTIMATED_TOKENS}


def test_a_refusal_from_the_model_still_counts_because_the_model_was_called(api, ledger):
    install(ledger, Counting(Completion("I don't know.", 1500, 5)))
    assert ask(api).json()["kind"] == "refusal"
    assert ledger.rows == {(DAY, PUBLIC): 1505}


def test_a_provider_failure_counts_nothing(api, ledger):
    install(ledger, Counting(error=RateLimited("429")))
    assert ask(api).json()["kind"] == "saved"
    assert ledger.rows == {}


def test_no_passages_means_no_model_call_and_nothing_counted(api, ledger):
    c = Counting()
    c.search = lambda vec, k: []
    install(ledger, c)
    assert ask(api).json()["kind"] == "refusal"
    assert c.model_calls == 0 and ledger.rows == {}


# --- a spent budget -----------------------------------------------------------------------------


def test_a_spent_public_budget_answers_saved_and_costs_nothing(api, ledger):
    ledger.rows[(DAY, PUBLIC)] = 700  # the public limit with total 1000 and 70%
    c = install(ledger)
    r = ask(api)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "saved" and body["reason"] == "budget_spent"
    assert "allowance" in body["notice"].lower() and body["saved"] == ITEMS
    assert (c.embeds, c.searches, c.model_calls) == (0, 0, 0)  # not even the embedding
    assert ledger.rows == {(DAY, PUBLIC): 700}  # nothing counted for a saved reply


def test_a_spent_budget_still_says_which_saved_answer_matches(api, ledger):
    ledger.rows[(DAY, PUBLIC)] = 700
    install(ledger)
    assert ask(api, "how do I restart the backend").json()["match"] == "restart"


# --- demo tokens --------------------------------------------------------------------------------


def test_a_demo_token_gets_live_answers_after_the_public_share_is_spent(api, ledger):
    ledger.rows[(DAY, PUBLIC)] = 900
    install(ledger)
    r = ask(api, token=TOKEN)
    assert r.status_code == 200 and r.json()["kind"] == "live"
    assert ledger.rows[(DAY, "owner")] == 1800  # counted under the token's NAME
    assert ledger.rows[(DAY, PUBLIC)] == 900  # not under the public share


def test_a_token_holder_stops_at_the_days_total(api, ledger):
    ledger.rows[(DAY, PUBLIC)] = 700
    ledger.rows[(DAY, "owner")] = 300  # 700 + 300 = the total
    c = install(ledger)
    body = ask(api, token=TOKEN).json()
    assert body["kind"] == "saved" and body["reason"] == "budget_spent"
    assert c.model_calls == 0


def test_a_token_does_not_lift_the_providers_own_limit(api, ledger):
    install(ledger, Counting(error=RateLimited("429")))
    body = ask(api, token=TOKEN).json()
    assert body["kind"] == "saved" and body["reason"] == "rate_limited"


def test_a_wrong_token_is_a_401_and_never_a_silent_downgrade(api, ledger, caplog):
    c = install(ledger)
    with caplog.at_level("INFO"):
        r = ask(api, token="w" * 64)
    assert r.status_code == 401
    assert r.json()["kind"] == "unauthorized" and r.json()["notice"]
    assert (c.embeds, c.model_calls) == (0, 0) and ledger.rows == {}
    assert "w" * 64 not in caplog.text and "w" * 64 not in r.text


def test_a_token_when_none_exist_is_a_401(api, ledger, monkeypatch):
    monkeypatch.setattr("app.main.TOKENS", DemoTokens(None))
    install(ledger)
    assert ask(api, token=TOKEN).status_code == 401


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_token_header_is_the_public(api, ledger, value):
    install(ledger)
    r = ask(api, token=value)
    assert r.status_code == 200 and (DAY, PUBLIC) in ledger.rows


def test_a_token_with_spaces_around_it_works(api, ledger):
    install(ledger)
    assert ask(api, token=f" {TOKEN} ").json()["kind"] == "live"
    assert (DAY, "owner") in ledger.rows


# --- the ledger and the database misbehaving -----------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        psycopg.errors.UndefinedTable('relation "llm_usage" does not exist'),
        psycopg.errors.InsufficientPrivilege("permission denied for table llm_usage"),
    ],
    ids=["no_table", "no_grant"],
)
def test_a_broken_ledger_does_not_stop_answering(api, ledger, caplog, error):
    ledger.fail_used = ledger.fail_add = error
    c = install(ledger)
    with caplog.at_level("INFO"):
        r = ask(api, "my very secret question about the ledger")
    assert r.status_code == 200 and r.json()["kind"] == "live" and c.model_calls == 1
    assert "budget_error" in caplog.text and type(error).__name__ in caplog.text
    assert "Traceback" not in caplog.text and "secret question" not in caplog.text


def test_a_database_that_is_down_fails_at_once_without_a_second_wait(api, ledger):
    # The budget check is the first database call. If the database is unreachable, retrieval
    # would fail too: answer 503 now instead of waiting for the pool a second time.
    ledger.fail_used = psycopg.OperationalError("connection refused")
    c = install(ledger)
    r = ask(api)
    assert r.status_code == 503
    assert r.json()["kind"] == "unavailable" and r.json()["reason"] == "index_unavailable"
    assert (c.embeds, c.searches, c.model_calls) == (0, 0, 0)


def test_failing_to_record_does_not_fail_the_answer(api, ledger, caplog):
    ledger.fail_add = psycopg.OperationalError("connection lost")
    install(ledger)
    with caplog.at_level("INFO"):
        r = ask(api)
    assert r.status_code == 200 and r.json()["kind"] == "live"
    assert "budget_error" in caplog.text


def test_the_slot_is_released_after_a_spent_budget(api, ledger):
    ledger.rows[(DAY, PUBLIC)] = 700
    install(ledger, max_concurrent=1)
    for _ in range(2):  # a leaked slot would turn the second one into "busy"
        assert ask(api).json()["reason"] == "budget_spent"


# --- logs ---------------------------------------------------------------------------------------


def test_the_log_line_names_who_asked_but_never_the_token_or_the_question(api, ledger, caplog):
    install(ledger)
    with caplog.at_level("INFO"):
        ask(api, "my very secret question about tokens", token=TOKEN)
        ask(api, "another very secret question about tokens")
    assert "who=owner" in caplog.text and "who=public" in caplog.text
    assert (
        TOKEN not in caplog.text and hashlib.sha256(TOKEN.encode()).hexdigest() not in caplog.text
    )
    assert "secret question" not in caplog.text


def test_a_spent_budget_is_logged_as_saved_with_its_reason(api, ledger, caplog):
    ledger.rows[(DAY, PUBLIC)] = 700
    install(ledger)
    with caplog.at_level("INFO"):
        ask(api)
    assert "kind=saved" in caplog.text and "reason=budget_spent" in caplog.text


def test_without_a_budget_nothing_changes(api):
    c = Counting()
    app.state.answerer = Answerer(
        c.embedder(), c.search, c.llm, model="m", saved=SavedAnswers(ITEMS)
    )
    assert ask(api).json()["kind"] == "live"
