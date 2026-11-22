"""Demo tokens (ADR 0003, point 7): a directory with one file per token. The file name is the
token's name, its content the SHA-256 of the token (lowercase hex). The cluster never holds a token.

The kubelet refreshes a mounted Secret in place, so a token added or revoked takes effect without a
restart: the directory is therefore read on every lookup, not cached.
"""

import hashlib
import hmac
import os

import pytest

from app.budget.tokens import DemoTokens


def sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


TOKEN_A = "a" * 64
TOKEN_B = "b" * 64


@pytest.fixture
def tokens_dir(tmp_path):
    (tmp_path / "owner").write_text(sha(TOKEN_A))
    (tmp_path / "reviewer-anna").write_text(sha(TOKEN_B))
    return tmp_path


def test_a_known_token_gives_its_name(tokens_dir):
    t = DemoTokens(tokens_dir)
    assert t.identify(TOKEN_A) == "owner"
    assert t.identify(TOKEN_B) == "reviewer-anna"


def test_an_unknown_token_gives_nothing(tokens_dir):
    t = DemoTokens(tokens_dir)
    assert t.identify("c" * 64) is None
    assert t.identify(TOKEN_A[:-1]) is None  # one character short
    assert t.identify(sha(TOKEN_A)) is None  # the HASH is not a token


def test_whitespace_around_a_token_is_ignored(tokens_dir):
    assert DemoTokens(tokens_dir).identify(f"  {TOKEN_A}\n") == "owner"


def test_no_directory_means_no_tokens(tmp_path):
    assert DemoTokens(None).identify(TOKEN_A) is None
    assert DemoTokens(tmp_path / "missing").identify(TOKEN_A) is None
    assert DemoTokens(tmp_path).identify(TOKEN_A) is None  # empty, as before the first is sealed


def test_a_revoked_token_stops_working_without_a_restart(tokens_dir):
    t = DemoTokens(tokens_dir)
    assert t.identify(TOKEN_B) == "reviewer-anna"
    (tokens_dir / "reviewer-anna").unlink()
    assert t.identify(TOKEN_B) is None
    assert t.identify(TOKEN_A) == "owner"


def test_a_token_added_later_works_at_once(tokens_dir):
    t = DemoTokens(tokens_dir)
    assert t.identify("c" * 64) is None
    (tokens_dir / "new-one").write_text(sha("c" * 64))
    assert t.identify("c" * 64) == "new-one"


def test_a_rotated_token_replaces_the_old_value(tokens_dir):
    t = DemoTokens(tokens_dir)
    (tokens_dir / "owner").write_text(sha("d" * 64))
    assert t.identify(TOKEN_A) is None
    assert t.identify("d" * 64) == "owner"


def test_files_that_are_not_token_hashes_are_ignored(tokens_dir):
    (tokens_dir / "Upper").write_text(sha("e" * 64))  # not a valid name
    (tokens_dir / "with.dot").write_text(sha("f" * 64))
    (tokens_dir / "short").write_text("abc123")  # not a SHA-256
    (tokens_dir / "notahex").write_text("z" * 64)
    (tokens_dir / ".hidden").write_text(
        sha("1" * 64)
    )  # the kubelet's bookkeeping starts with a dot
    (tokens_dir / "adir").mkdir()
    t = DemoTokens(tokens_dir)
    for token in ("e" * 64, "f" * 64, "1" * 64):
        assert t.identify(token) is None
    assert t.identify(TOKEN_A) == "owner"  # and the good ones still work


def test_a_hash_with_a_trailing_newline_or_capitals_is_still_read(tokens_dir):
    (tokens_dir / "owner").write_text(sha(TOKEN_A).upper() + "\n")
    assert DemoTokens(tokens_dir).identify(TOKEN_A) == "owner"


def test_the_kubelets_symlink_layout_is_read(tmp_path):
    # A mounted Secret is: ..data -> ..<timestamp>/, and each token a symlink into ..data.
    stamp = tmp_path / "..2026_11_23"
    stamp.mkdir()
    (stamp / "owner").write_text(sha(TOKEN_A))
    try:
        os.symlink("..2026_11_23", tmp_path / "..data")
        os.symlink("..data/owner", tmp_path / "owner")
    except OSError:
        pytest.skip("cannot create symlinks here")
    assert DemoTokens(tmp_path).identify(TOKEN_A) == "owner"


def test_every_token_is_compared_so_the_time_does_not_say_which_matched(tokens_dir, monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    assert DemoTokens(tokens_dir).identify(TOKEN_A) == "owner"
    assert len(calls) == 2  # both files, though the first already matched


def test_neither_the_token_nor_its_hash_is_logged(tokens_dir, caplog):
    (tokens_dir / "broken").write_text("not a hash")
    with caplog.at_level("DEBUG"):
        DemoTokens(tokens_dir).identify(TOKEN_A)
        DemoTokens(tokens_dir).identify("c" * 64)
    assert TOKEN_A not in caplog.text and sha(TOKEN_A) not in caplog.text
    assert "c" * 64 not in caplog.text
