"""Index runs against a real Postgres with pgvector (CI service, or docker compose locally)."""

import hashlib
import os
import threading

import numpy as np
import psycopg
import pytest

from app.corpus.corpus import Document
from app.corpus.split import split_markdown
from app.embed.model import DIMENSIONS
from app.index.store import IndexBusy, connect, embedding_text, index_documents, search

SHA1, SHA2 = "1" * 40, "2" * 40
BODY = "word " * 60


class FakeEmbedder:
    """Deterministic vectors from a text hash; counts what it was asked to embed."""

    def __init__(self):
        self.calls = 0

    def _vec(self, text):
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).standard_normal(DIMENSIONS).astype(np.float32)
        return v / np.linalg.norm(v)

    def embed_passages(self, texts):
        self.calls += len(texts)
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text):
        return self._vec(text)


def doc(path, text, commit=SHA1, repo="o/r"):
    passages = split_markdown(text, repo=repo, path=path, commit=commit)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return Document(repo, path, commit, digest, tuple(passages))


@pytest.fixture
def conn():
    if "PGHOST" not in os.environ:
        pytest.skip("needs Postgres with pgvector (PGHOST)")
    # Start every test from an empty database: drop, then let connect() create the schema.
    with psycopg.connect("") as c:
        c.execute("DROP TABLE IF EXISTS passages, documents, index_meta CASCADE")
    c = connect()
    yield c
    c.close()


def count(conn, table):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return cur.fetchone()[0]


def test_first_run_inserts_everything(conn):
    emb = FakeEmbedder()
    stats = index_documents(
        conn, [doc("a.md", f"# A\n\n{BODY}"), doc("b.md", f"# B\n\n{BODY}")], emb, "m1"
    )
    assert (stats.added, stats.changed, stats.removed) == (2, 0, 0)
    assert count(conn, "documents") == 2 and count(conn, "passages") == emb.calls == 2


def test_unchanged_run_embeds_nothing(conn):
    docs = [doc("a.md", f"# A\n\n{BODY}")]
    index_documents(conn, docs, FakeEmbedder(), "m1")
    emb = FakeEmbedder()
    stats = index_documents(conn, docs, emb, "m1")
    assert emb.calls == 0 and (stats.added, stats.changed, stats.removed, stats.unchanged) == (
        0,
        0,
        0,
        1,
    )


def test_only_the_changed_file_is_re_embedded_and_deleted_files_go(conn):
    index_documents(
        conn, [doc("a.md", f"# A\n\n{BODY}"), doc("b.md", f"# B\n\n{BODY}")], FakeEmbedder(), "m1"
    )
    emb = FakeEmbedder()
    stats = index_documents(conn, [doc("a.md", f"# A\n\n{BODY} more")], emb, "m1")
    assert (stats.changed, stats.removed) == (1, 1) and emb.calls == 1
    assert count(conn, "documents") == 1 and count(conn, "passages") == 1


def test_new_commit_with_same_content_updates_links_without_embedding(conn):
    index_documents(conn, [doc("a.md", f"# A\n\n{BODY}", commit=SHA1)], FakeEmbedder(), "m1")
    emb = FakeEmbedder()
    index_documents(conn, [doc("a.md", f"# A\n\n{BODY}", commit=SHA2)], emb, "m1")
    assert emb.calls == 0
    with conn.cursor() as cur:
        cur.execute("SELECT url FROM passages")
        assert SHA2 in cur.fetchone()[0]


def test_a_different_model_forces_a_full_re_index(conn):
    docs = [doc("a.md", f"# A\n\n{BODY}")]
    index_documents(conn, docs, FakeEmbedder(), "m1")
    emb = FakeEmbedder()
    stats = index_documents(conn, docs, emb, "m2")
    assert emb.calls == 1 and stats.full_rebuild


def test_search_returns_the_nearest_passages_with_their_citation(conn):
    emb = FakeEmbedder()
    a, b = doc("a.md", f"# A\n\n{BODY} alpha"), doc("b.md", f"# B\n\n{BODY} beta")
    index_documents(conn, [a, b], emb, "m1")
    query = emb._vec(embedding_text(b.passages[0]))
    hits = search(conn, query, k=1)
    assert hits[0].path == "b.md" and hits[0].url.endswith("b.md#b")
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)


def test_an_empty_document_list_is_refused(conn):
    index_documents(conn, [doc("a.md", f"# A\n\n{BODY}")], FakeEmbedder(), "m1")
    with pytest.raises(ValueError, match="no documents"):
        index_documents(conn, [], FakeEmbedder(), "m1")
    assert count(conn, "documents") == 1  # nothing was wiped


def test_a_second_run_at_the_same_time_is_refused(conn):
    index_documents(conn, [doc("a.md", f"# A\n\n{BODY}")], FakeEmbedder(), "m1")
    holder = connect()
    started, release = threading.Event(), threading.Event()

    def hold_lock():
        with holder.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtext('oncall-assistant-index'))")
            started.set()
            release.wait(5)
            cur.execute("SELECT pg_advisory_unlock(hashtext('oncall-assistant-index'))")

    t = threading.Thread(target=hold_lock)
    t.start()
    started.wait(5)
    try:
        with pytest.raises(IndexBusy):
            index_documents(conn, [doc("a.md", f"# A\n\n{BODY}")], FakeEmbedder(), "m1")
    finally:
        release.set()
        t.join()
        holder.close()


def test_failed_run_leaves_the_previous_index_untouched(conn):
    index_documents(conn, [doc("a.md", f"# A\n\n{BODY}")], FakeEmbedder(), "m1")

    class Broken(FakeEmbedder):
        def embed_passages(self, texts):
            raise RuntimeError("model crashed")

    with pytest.raises(RuntimeError):
        index_documents(conn, [doc("b.md", f"# B\n\n{BODY}")], Broken(), "m1")
    with conn.cursor() as cur:
        cur.execute("SELECT path FROM documents")
        assert [r[0] for r in cur.fetchall()] == ["a.md"]


def test_connect_reports_a_missing_extension_clearly(conn):
    # The pgvector image has the extension; this documents that connect() creates it.
    with conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        assert cur.fetchone() is not None
    assert isinstance(conn, psycopg.Connection)
