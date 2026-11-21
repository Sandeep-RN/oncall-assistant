import json

import pytest

from app.corpus.corpus import build, read_lock, write_jsonl
from app.corpus.fetch import FetchError
from app.corpus.sources import Source
from tests.corpus.helpers import SHA, FakeGet, make_tarball

BODY = "word " * 60


def routes(files):
    return {"/commits/main": SHA.encode(), f"/tar.gz/{SHA}": make_tarball(files)}


def test_build_returns_documents_with_passages_and_a_file_hash():
    docs = build([Source("o/r")], {"o/r": SHA}, get=FakeGet(routes({"a.md": f"# T\n\n{BODY}\n"})))
    assert [d.path for d in docs] == ["a.md"]
    assert docs[0].commit == SHA and len(docs[0].content_hash) == 64
    assert docs[0].passages[0].url.endswith(f"/{SHA}/a.md#t")


def test_same_content_gives_the_same_hash_and_changed_content_a_different_one():
    one = build([Source("o/r")], {"o/r": SHA}, get=FakeGet(routes({"a.md": f"# T\n\n{BODY}\n"})))
    two = build([Source("o/r")], {"o/r": SHA}, get=FakeGet(routes({"a.md": f"# T\n\n{BODY}\n"})))
    three = build(
        [Source("o/r")], {"o/r": SHA}, get=FakeGet(routes({"a.md": f"# T\n\n{BODY} x\n"}))
    )
    assert one[0].content_hash == two[0].content_hash != three[0].content_hash


def test_a_repo_with_no_documents_is_an_error_not_an_empty_corpus():
    with pytest.raises(FetchError, match="no documents"):
        build([Source("o/r")], {"o/r": SHA}, get=FakeGet(routes({"main.tf": "x"})))


def test_jsonl_has_one_line_per_passage_and_is_written_atomically(tmp_path):
    docs = build([Source("o/r")], {"o/r": SHA}, get=FakeGet(routes({"a.md": f"# T\n\n{BODY}\n"})))
    out = tmp_path / "out" / "corpus.jsonl"
    write_jsonl(docs, out)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert {
        "id",
        "repo",
        "path",
        "heading_path",
        "anchor",
        "url",
        "commit",
        "text",
        "file_hash",
    } <= set(rows[0])
    assert not list(out.parent.glob("*.tmp"))


def test_lock_file_round_trip_and_validation(tmp_path):
    lock = tmp_path / "corpus-lock.json"
    lock.write_text(json.dumps({"o/r": SHA}), encoding="utf-8")
    assert read_lock(lock) == {"o/r": SHA}
    lock.write_text(json.dumps({"o/r": "main"}), encoding="utf-8")
    with pytest.raises(FetchError, match="not a commit"):
        read_lock(lock)
