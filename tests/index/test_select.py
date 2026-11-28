# Same-document expansion of the retrieved passages (issue #74, ADR 0004).
import pytest

from app.index.select import CANDIDATES, EXTRA, NEED, same_document
from app.index.store import Hit


def hit(n, path="docs/a.md", repo="o/r"):
    return Hit(f"id{n}", repo, path, ("Doc", f"Section {n}"), f"https://x/{n}", "text", 1 - n / 100)


def ids(hits):
    return [h.id for h in hits]


def test_the_defaults_are_the_measured_ones():
    # Measured on the whole eval set on 2026-11-28 (issue #74): 4 of 5, up to 3 more, from 20.
    assert (NEED, EXTRA, CANDIDATES) == (4, 3, 20)


def test_when_the_top_five_are_spread_over_documents_nothing_is_added():
    cands = [
        hit(1, "a.md"),
        hit(2, "b.md"),
        hit(3, "a.md"),
        hit(4, "c.md"),
        hit(5, "a.md"),
        hit(6, "a.md"),
        hit(7, "a.md"),
    ]
    assert ids(same_document(cands)) == ["id1", "id2", "id3", "id4", "id5"]


def test_when_four_of_five_share_a_document_its_next_sections_are_added_in_rank_order():
    cands = [
        hit(1, "a.md"),
        hit(2, "a.md"),
        hit(3, "b.md"),
        hit(4, "a.md"),
        hit(5, "a.md"),
        hit(6, "c.md"),
        hit(7, "a.md"),
        hit(8, "b.md"),
        hit(9, "a.md"),
    ]
    assert ids(same_document(cands)) == ["id1", "id2", "id3", "id4", "id5", "id7", "id9"]


def test_at_most_three_are_added():
    cands = [hit(n) for n in range(1, 21)]
    assert ids(same_document(cands)) == [f"id{n}" for n in range(1, 9)]


def test_the_same_path_in_another_repo_is_another_document():
    cands = [hit(n) for n in range(1, 6)] + [hit(6, repo="o/other"), hit(7)]
    assert ids(same_document(cands))[5:] == ["id7"]


def test_candidates_past_the_limit_are_never_used():
    cands = [hit(n) for n in range(1, 6)] + [hit(n, "z.md") for n in range(6, 21)] + [hit(21)]
    assert len(same_document(cands)) == 5


def test_fewer_than_five_candidates_come_back_unchanged():
    assert ids(same_document([hit(1), hit(2)])) == ["id1", "id2"]
    assert same_document([]) == []


@pytest.mark.parametrize("need,extra", [(5, 3), (4, 0)])
def test_the_rule_can_be_tightened_or_switched_off(need, extra):
    cands = [hit(1, "b.md")] + [hit(n) for n in range(2, 9)]
    out = same_document(cands, need=need, extra=extra)
    assert len(out) == 5
