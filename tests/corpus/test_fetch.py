import pytest

from app.corpus.fetch import FetchError, iter_markdown, resolve_commit, with_retries
from app.corpus.sources import Source
from tests.corpus.helpers import SHA, FakeGet, make_tarball

DOC = "# T\n\nhello\n"


def test_resolve_commit_returns_the_sha():
    get = FakeGet({"/commits/main": SHA.encode()})
    assert resolve_commit("o/r", "main", get=get) == SHA


def test_resolve_commit_rejects_anything_that_is_not_a_sha():
    get = FakeGet({"/commits/main": b"<html>rate limited</html>"})
    with pytest.raises(FetchError):
        resolve_commit("o/r", "main", get=get)


def test_only_matching_regular_markdown_files_are_read():
    tar = make_tarball(
        {
            "README.md": DOC,
            "docs/adr/0001-x.md": DOC,
            "CLAUDE.md": DOC,  # excluded by the source
            "docs/agents/issue-tracker.md": DOC,  # excluded
            "main.tf": "resource {}",  # not markdown
        }
    )
    get = FakeGet({f"/tar.gz/{SHA}": tar})
    paths = [p for p, _ in iter_markdown(Source("o/r"), SHA, get=get)]
    assert sorted(paths) == ["README.md", "docs/adr/0001-x.md"]  # symlink linked.md skipped


def test_oversized_and_undecodable_files_are_skipped():
    tar = make_tarball({"big.md": "x" * 2000, "bad.md": b"\xff\xfe\x00bad", "ok.md": DOC})
    get = FakeGet({f"/tar.gz/{SHA}": tar})
    found = dict(iter_markdown(Source("o/r"), SHA, get=get, max_file_bytes=1000))
    assert list(found) == ["ok.md"]


def test_download_larger_than_the_cap_fails():
    get = FakeGet({f"/tar.gz/{SHA}": make_tarball({"a.md": DOC})})
    with pytest.raises(FetchError, match="larger than"):
        list(iter_markdown(Source("o/r"), SHA, get=get, max_download_bytes=10))


def test_retries_then_succeeds():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("connection reset")
        return "ok"

    assert with_retries(flaky, attempts=3, sleep=lambda s: None) == "ok"


def test_retries_give_up_with_a_clear_error():
    def always():
        raise OSError("down")

    with pytest.raises(FetchError, match="down"):
        with_retries(always, attempts=2, sleep=lambda s: None)
