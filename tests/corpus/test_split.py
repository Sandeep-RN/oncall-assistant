from app.corpus.split import github_slug, split_markdown

URL = "https://github.com/o/r/blob/{commit}/{path}"
COMMON = {"repo": "o/r", "path": "docs/a.md", "commit": "c0ffee"}


def passages(text, **kw):
    return split_markdown(text, **COMMON, **kw)


def test_slug_follows_github_rules():
    assert github_slug("1. Open the tunnel") == "1-open-the-tunnel"
    assert github_slug("Rebuild proof (#57): same VM") == "rebuild-proof-57-same-vm"
    assert github_slug("The `kubectl` [link](http://x) step") == "the-kubectl-link-step"


def test_headings_become_paths_and_anchors():
    text = "# Title\n\n" + "intro word " * 50 + "\n\n## Part one\n\n" + "body word " * 50
    ps = passages(text)
    assert [p.heading_path for p in ps] == [("Title",), ("Title", "Part one")]
    assert ps[1].anchor == "part-one"
    assert ps[1].url == "https://github.com/o/r/blob/c0ffee/docs/a.md#part-one"


def test_hash_lines_inside_code_fences_are_not_headings():
    text = (
        "# T\n\n## Step\n\n"
        + "word " * 50
        + "\n\n```bash\n# a shell comment\n\n# another\nls\n```\n"
    )
    ps = passages(text)
    assert [p.heading_path for p in ps] == [("T", "Step")]
    assert "# a shell comment" in ps[0].text and "# another" in ps[0].text


def test_long_section_is_split_between_blocks_never_inside_a_fence():
    para = ("word " * 120).strip()
    fence = "```\n" + "\n\n".join(["code line"] * 5) + "\n```"
    text = f"# T\n\n{para}\n\n{para}\n\n{para}\n\n{fence}\n"
    ps = passages(text, max_words=300)
    assert len(ps) >= 2
    assert all(p.heading_path == ("T",) for p in ps)
    assert sum(p.text.count("```") for p in ps) == 2
    assert any(p.text.count("```") == 2 for p in ps)  # the fence is whole in one passage
    assert [p.ordinal for p in ps] == list(range(len(ps)))


def test_tiny_section_is_merged_into_the_next_one():
    text = "# T\n\n## Short\n\nonly a few words\n\n## Long\n\n" + "word " * 80
    ps = passages(text, min_words=40)
    assert len(ps) == 1
    assert "only a few words" in ps[0].text and "## Short" in ps[0].text
    assert ps[0].heading_path == ("T", "Long")


def test_trailing_tiny_section_is_kept():
    ps = passages("# T\n\n" + "word " * 80 + "\n\n## End\n\nshort tail\n", min_words=40)
    assert "short tail" in ps[-1].text


def test_duplicate_headings_get_numbered_anchors():
    body = "word " * 60
    ps = passages(f"# T\n\n## Same\n\n{body}\n\n## Same\n\n{body}\n")
    assert [p.anchor for p in ps] == ["same", "same-1"]


def test_empty_and_heading_only_documents_yield_nothing():
    assert passages("") == []
    assert passages("# Only a title\n") == []


def test_ids_are_stable_and_unique():
    body = "word " * 60
    text = f"# T\n\n## A\n\n{body}\n\n## B\n\n{body}\n"
    a, b = passages(text), passages(text)
    assert [p.id for p in a] == [p.id for p in b]
    assert len({p.id for p in a}) == len(a)


def test_tiny_trailing_chunk_is_merged_into_the_previous_passage():
    # An uncuttable block (a table) over the limit, then a short closing paragraph.
    table = "\n".join(["| a | b |", "|---|---|"] + [f"| {'w ' * 20}| {i} |" for i in range(20)])
    ps = passages(f"# T\n\n{table}\n\nlast short line\n", max_words=300, min_words=40)
    assert len(ps) == 1
    assert ps[0].text.endswith("last short line")


def test_long_plain_block_is_cut_at_line_boundaries():
    lines = "\n".join(f"- item {i} " + "word " * 20 for i in range(30))  # one block, ~700 words
    ps = passages(f"# T\n\n{lines}\n", max_words=300)
    assert len(ps) >= 2
    assert all(p.words <= 300 for p in ps)
    joined = "\n".join(p.text for p in ps)
    assert all(f"- item {i} " in joined for i in range(30))  # nothing lost


def test_long_table_is_never_cut():
    table = "\n".join(["| a | b |", "|---|---|"] + [f"| {'w ' * 20}| {i} |" for i in range(40)])
    ps = passages(f"# T\n\n{table}\n", max_words=100)
    assert len(ps) == 1 and ps[0].text.count("\n") == 41


def test_short_lead_in_stays_with_the_big_table_that_follows():
    table = "\n".join(["| a | b |", "|---|---|"] + [f"| {'w ' * 20}| {i} |" for i in range(20)])
    ps = passages(f"# T\n\nEach one happened.\n\n{table}\n", max_words=300, min_words=40)
    assert len(ps) == 1 and ps[0].text.startswith("Each one happened.")
