"""One index run: what the nightly CronJob (and an on-demand Job) executes.

    python -m app.index            # each repo's current head
    python -m app.index --lock corpus-lock.json   # the pinned commits instead

Exit codes: 0 done, 1 a problem to look at (fetch, database, model), 2 another run holds the lock.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg

from app.corpus.corpus import build, read_lock
from app.corpus.fetch import FetchError, resolve_commit
from app.corpus.sources import SOURCES
from app.embed.model import DEFAULT_DIR, OnnxEmbedder, model_key
from app.index.store import IndexBusy, connect, index_documents


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.index")
    ap.add_argument("--lock", type=Path, help="use the commits pinned in this file")
    ap.add_argument("--model-dir", type=Path, default=DEFAULT_DIR)
    args = ap.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    started = time.monotonic()
    try:
        if args.lock:
            commits = read_lock(args.lock)
        else:
            commits = {s.repo: resolve_commit(s.repo, s.ref, token=token) for s in SOURCES}
        docs = build(SOURCES, commits, token=token)
        embedder = OnnxEmbedder(args.model_dir)
        with connect() as conn:
            stats = index_documents(conn, docs, embedder, model_key())
    except IndexBusy as e:
        print(f"skipped: {e}", file=sys.stderr)
        return 2
    except (FetchError, OSError, ValueError, psycopg.Error) as e:
        # psycopg.Error is not an OSError: it needs its own entry, or a database outage would
        # end in a traceback instead of one clear line.
        print(f"error: {e}", file=sys.stderr)
        return 1
    rebuilt = ", full rebuild (model changed)" if stats.full_rebuild else ""
    print(
        f"indexed in {time.monotonic() - started:.1f}s: {stats.added} added,"
        f" {stats.changed} changed, {stats.removed} removed, {stats.unchanged} unchanged,"
        f" {stats.passages_embedded} passages embedded{rebuilt}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
