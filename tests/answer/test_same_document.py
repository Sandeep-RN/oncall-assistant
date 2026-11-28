# The answerer and the eval use the same expansion rule (issue #74), so the eval scores what a
# visitor gets.
import numpy as np

from app.answer.llm import Completion
from app.answer.service import Answerer
from app.evals.questions import Question, Source
from app.evals.retrieval import render
from app.evals.score import evaluate
from app.index.select import CANDIDATES, same_document
from app.index.store import Hit


def hit(n, path="docs/a.md"):
    return Hit(f"id{n}", "o/r", path, ("Doc", f"S{n}"), f"https://x/{n}", f"text {n}", 1 - n / 100)


CANDS = [hit(n) for n in range(1, 21)]


class FakeEmbedder:
    def embed_query(self, text):
        return np.zeros(384, dtype=np.float32)


def run(same_doc):
    asked, sent = [], []

    def search(vec, k):
        asked.append(k)
        return CANDS[:k]

    def llm(messages):
        sent.append(messages[1]["content"])
        return Completion("It is in the doc [7].", 10, 5)

    a = Answerer(FakeEmbedder(), search, llm, model="m", same_document=same_doc)
    return a.ask("q?"), asked, sent


def test_off_asks_for_five_passages_and_sends_five():
    answer, asked, sent = run(False)
    assert asked == [5] and "[6]" not in sent[0]
    assert answer.kind == "refusal"  # [7] does not exist: uncited


def test_on_asks_for_the_candidates_and_sends_the_expanded_set():
    answer, asked, sent = run(True)
    assert asked == [CANDIDATES] and "[8]" in sent[0] and "[9]" not in sent[0]
    assert answer.kind == "live" and answer.citations[0]["url"] == "https://x/7"


def test_the_eval_counts_a_passage_found_by_the_expansion():
    q = Question("A01", "answerable", "q?", (Source("o/r", "docs/a.md", "S7"),), "g")
    plain = evaluate([q], lambda text: CANDS, k=5)
    expanded = evaluate([q], lambda text: same_document(CANDS), k=5, extra=3)
    assert plain.found == 0 and expanded.found == 1 and expanded.results[0].rank == 7
    assert "plus up to 3" in render(expanded) and "plus up to" not in render(plain)


def test_the_app_turns_the_rule_on_unless_the_kill_switch_says_off(monkeypatch):
    from app.main import SAME_DOCUMENT_FLAG, same_document_setting

    monkeypatch.delenv(SAME_DOCUMENT_FLAG, raising=False)
    assert same_document_setting() is True
    for value, expected in (
        ("off", False),
        (" OFF ", False),
        ("on", True),
        ("of", True),
        ("", True),
    ):
        monkeypatch.setenv(SAME_DOCUMENT_FLAG, value)
        assert same_document_setting() is expected, value
