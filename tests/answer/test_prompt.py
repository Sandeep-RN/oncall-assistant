from app.answer.prompt import MAX_PASSAGE_WORDS, build_messages, parse_answer
from app.index.store import Hit


def hits(n=3):
    return [
        Hit(
            f"id{i}",
            "o/r",
            f"docs/{i}.md",
            ("Runbook", f"Step {i}"),
            f"https://x/{i}",
            f"text {i}",
            0.8,
        )
        for i in range(1, n + 1)
    ]


def test_passages_are_numbered_with_their_heading_path_and_the_question_comes_last():
    system, user = build_messages("How do I restart?", hits(2))
    assert system["role"] == "system" and "I don't know" in system["content"]
    text = user["content"]
    assert text.index("[1] Runbook > Step 1") < text.index("[2] Runbook > Step 2")
    assert text.rstrip().endswith("Question: How do I restart?")


def test_long_passages_are_cut_to_bound_the_tokens():
    long_hit = [Hit("x", "o/r", "a.md", ("T",), "u", "word " * 2000, 0.8)]
    _, user = build_messages("q", long_hit)
    assert user["content"].count("word") <= MAX_PASSAGE_WORDS


def test_cited_answer_is_live_with_its_citations_in_order():
    p = parse_answer("Delete the pod [2]. Then check the logs [1][2].", k=3)
    assert p.kind == "live" and p.cited == [2, 1]


def test_grouped_citations_are_understood():
    assert parse_answer("Both apply [1, 3].", k=3).cited == [1, 3]


def test_citation_numbers_that_are_not_passages_are_dropped():
    p = parse_answer("Restart it [7] and check [2].", k=3)
    assert p.kind == "live" and p.cited == [2]


def test_an_answer_without_any_valid_citation_becomes_a_refusal():
    for text in ("Just restart the node.", "Restart it [9]."):
        p = parse_answer(text, k=3)
        assert p.kind == "refusal" and p.reason == "uncited" and p.cited == []


def test_the_model_saying_it_does_not_know_is_a_refusal():
    for text in ("I don't know.", "I don’t know", "i don't know: the passages do not cover it"):
        p = parse_answer(text, k=3)
        assert p.kind == "refusal" and p.reason == "model"


def test_a_refusal_with_citations_is_still_a_refusal():
    # "I don't know [1]" must not be shown as an answer just because it cites something.
    assert parse_answer("I don't know [1].", k=3).kind == "refusal"


def test_gpt_oss_style_citations_are_accepted_and_shown_as_square_brackets():
    # Real replies from gpt-oss-120b (2026-11-22): it cites with fullwidth brackets.
    p = parse_answer("Revert the tag-bump PR in Git (self-heal)【1】.", k=5)
    assert p.kind == "live" and p.cited == [1]
    assert p.answer == "Revert the tag-bump PR in Git (self-heal)[1]."
    p = parse_answer(
        "There is no point-in-time recovery【2†L3-L5】 and backups are dumps【1, 2】.", k=5
    )
    assert p.cited == [2, 1]
    assert "【" not in p.answer and "[2]" in p.answer and "[1][2]" in p.answer


def test_unknown_numbers_in_fullwidth_brackets_are_dropped_too():
    assert parse_answer("Restart it【9】.", k=3).reason == "uncited"
