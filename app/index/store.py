"""The passage index in Postgres with pgvector: schema, one index run, and search.

A run is ONE transaction under an advisory lock: readers keep seeing the previous index until it
commits, a failure leaves the previous index untouched, and two runs never overlap. Only new or
changed files are embedded (compared by content hash); a different model rebuilds everything.

Search is exact (a scan of every vector). At a few hundred passages that takes well under a
millisecond; an approximate index (HNSW) becomes worth it at roughly 10k to 50k passages.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import psycopg

from app.corpus.corpus import Document
from app.corpus.split import Passage
from app.embed.model import DIMENSIONS, Embedder

LOCK_KEY = "oncall-assistant-index"

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS index_meta (
    key   text PRIMARY KEY,
    value text NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    repo         text NOT NULL,
    path         text NOT NULL,
    commit       text NOT NULL,
    content_hash text NOT NULL,
    indexed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repo, path)
);
CREATE TABLE IF NOT EXISTS passages (
    id           text PRIMARY KEY,
    repo         text NOT NULL,
    path         text NOT NULL,
    ordinal      int  NOT NULL,
    heading_path text[] NOT NULL,
    anchor       text NOT NULL,
    url          text NOT NULL,
    commit       text NOT NULL,
    text         text NOT NULL,
    words        int  NOT NULL,
    embedding    vector({DIMENSIONS}) NOT NULL,
    FOREIGN KEY (repo, path) REFERENCES documents (repo, path) ON DELETE CASCADE
);
"""


class IndexBusy(RuntimeError):
    """Another index run holds the lock."""


@dataclass
class Stats:
    added: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    passages_embedded: int = 0
    full_rebuild: bool = False


@dataclass(frozen=True)
class Hit:
    id: str
    repo: str
    path: str
    heading_path: tuple[str, ...]
    url: str
    text: str
    score: float  # cosine similarity, 1.0 = same direction


def connect(conninfo: str | None = None) -> psycopg.Connection:
    """Connect (DATABASE_URL, or the standard PG* variables) and make sure the schema exists."""
    conn = psycopg.connect(conninfo if conninfo is not None else os.environ.get("DATABASE_URL", ""))
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()
    return conn


def embedding_text(p: Passage) -> str:
    """What the model reads for a passage: its heading path gives the text its context."""
    return " > ".join(p.heading_path) + "\n\n" + p.text


def _vector(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v.tolist()) + "]"


def _insert(cur: psycopg.Cursor, doc: Document, vectors: np.ndarray) -> None:
    cur.execute(
        "INSERT INTO documents (repo, path, commit, content_hash) VALUES (%s, %s, %s, %s)",
        (doc.repo, doc.path, doc.commit, doc.content_hash),
    )
    cur.executemany(
        "INSERT INTO passages (id, repo, path, ordinal, heading_path, anchor, url, commit, text,"
        " words, embedding) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
        [
            (
                p.id,
                p.repo,
                p.path,
                p.ordinal,
                list(p.heading_path),
                p.anchor,
                p.url,
                p.commit,
                p.text,
                p.words,
                _vector(v),
            )
            for p, v in zip(doc.passages, vectors, strict=True)
        ],
    )


def index_documents(
    conn: psycopg.Connection, docs: Sequence[Document], embedder: Embedder, model_key: str
) -> Stats:
    if not docs:
        # An empty fetch must never look like "every document was deleted".
        raise ValueError("no documents: refusing to empty the index")
    stats = Stats()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
            if not cur.fetchone()[0]:
                raise IndexBusy("another index run is in progress")

            cur.execute("SELECT value FROM index_meta WHERE key = 'model'")
            row = cur.fetchone()
            if row is None or row[0] != model_key:
                stats.full_rebuild = row is not None
                cur.execute("DELETE FROM documents")  # passages go with them (cascade)
                cur.execute(
                    "INSERT INTO index_meta (key, value) VALUES ('model', %s)"
                    " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (model_key,),
                )

            cur.execute("SELECT repo, path, content_hash, commit FROM documents")
            existing = {(r[0], r[1]): (r[2], r[3]) for r in cur.fetchall()}

            to_embed: list[Document] = []
            for d in docs:
                old = existing.get((d.repo, d.path))
                if old is None:
                    stats.added += 1
                    to_embed.append(d)
                elif old[0] != d.content_hash:
                    stats.changed += 1
                    cur.execute(
                        "DELETE FROM documents WHERE repo = %s AND path = %s", (d.repo, d.path)
                    )
                    to_embed.append(d)
                else:
                    stats.unchanged += 1
                    if old[1] != d.commit:
                        # Same text at a newer commit: move the permalinks, keep the vectors.
                        cur.execute(
                            "UPDATE documents SET commit = %s, indexed_at = now()"
                            " WHERE repo = %s AND path = %s",
                            (d.commit, d.repo, d.path),
                        )
                        cur.executemany(
                            "UPDATE passages SET commit = %s, url = %s WHERE id = %s",
                            [(p.commit, p.url, p.id) for p in d.passages],
                        )

            gone = set(existing) - {(d.repo, d.path) for d in docs}
            for repo, path in sorted(gone):
                cur.execute("DELETE FROM documents WHERE repo = %s AND path = %s", (repo, path))
            stats.removed = len(gone)

            texts = [embedding_text(p) for d in to_embed for p in d.passages]
            vectors = embedder.embed_passages(texts) if texts else np.empty((0, DIMENSIONS))
            stats.passages_embedded = len(texts)
            start = 0
            for d in to_embed:
                n = len(d.passages)
                _insert(cur, d, vectors[start : start + n])
                start += n
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return stats


def search(conn: psycopg.Connection, query: np.ndarray, *, k: int = 5) -> list[Hit]:
    vec = _vector(query)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, repo, path, heading_path, url, text, 1 - (embedding <=> %s::vector)"
            " FROM passages ORDER BY embedding <=> %s::vector LIMIT %s",
            (vec, vec, k),
        )
        rows = cur.fetchall()
    conn.commit()  # end the read transaction; a long-lived connection must not hold one open
    return [Hit(r[0], r[1], r[2], tuple(r[3]), r[4], r[5], float(r[6])) for r in rows]
