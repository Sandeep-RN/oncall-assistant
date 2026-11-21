"""Build the corpus: documents -> passages -> one JSONL line per passage.

    python -m app.corpus --lock corpus-lock.json --out data/corpus.jsonl
    python -m app.corpus --lock corpus-lock.json --update-lock   # pin each repo's current head

The lock file pins one commit per repo, so the eval set and the corpus stay in step. The nightly
indexing job (issue #4) resolves the heads itself and compares each file's hash with the database,
so it re-indexes only what changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.corpus.fetch import FetchError, Get, http_get, iter_markdown, resolve_commit
from app.corpus.sources import SOURCES, Source
from app.corpus.split import Passage, split_markdown

_HEX = set("0123456789abcdef")


@dataclass(frozen=True)
class Document:
    repo: str
    path: str
    commit: str
    content_hash: str  # sha256 of the file's text: "has this file changed?"
    passages: tuple[Passage, ...]


def build(
    sources: tuple[Source, ...] | list[Source],
    commits: dict[str, str],
    *,
    get: Get = http_get,
    token: str | None = None,
) -> list[Document]:
    docs: list[Document] = []
    for source in sources:
        sha = commits[source.repo]
        found = 0
        for path, text in iter_markdown(source, sha, get=get, token=token):
            found += 1
            passages = split_markdown(text, repo=source.repo, path=path, commit=sha)
            digest = hashlib.sha256(text.encode()).hexdigest()
            docs.append(Document(source.repo, path, sha, digest, tuple(passages)))
        if not found:
            # A silent empty corpus would make every answer a refusal; stop instead.
            raise FetchError(f"{source.repo}@{sha[:7]}: no documents matched; check the patterns")
    docs.sort(key=lambda d: (d.repo, d.path))
    return docs


def write_jsonl(docs: list[Document], out: Path) -> int:
    """Write atomically (temp file, then rename): a crash never leaves a half file."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    n = 0
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for d in docs:
            for p in d.passages:
                row = {
                    "id": p.id,
                    "repo": p.repo,
                    "path": p.path,
                    "heading_path": list(p.heading_path),
                    "anchor": p.anchor,
                    "url": p.url,
                    "commit": p.commit,
                    "ordinal": p.ordinal,
                    "words": p.words,
                    "text": p.text,
                    "file_hash": d.content_hash,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                n += 1
    os.replace(tmp, out)
    return n


def read_lock(path: Path) -> dict[str, str]:
    lock = json.loads(path.read_text(encoding="utf-8"))
    for repo, sha in lock.items():
        if len(sha) != 40 or not set(sha) <= _HEX:
            raise FetchError(f"{path}: {repo} is not a commit SHA ({sha!r}); use --update-lock")
    return lock


def write_lock(path: Path, lock: dict[str, str]) -> None:
    path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.corpus", description="Build the corpus.")
    ap.add_argument("--lock", type=Path, default=Path("corpus-lock.json"))
    ap.add_argument("--update-lock", action="store_true", help="pin each repo's current head")
    ap.add_argument("--out", type=Path, default=Path("data/corpus.jsonl"))
    args = ap.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")  # optional; public repos need none
    try:
        if args.update_lock or not args.lock.exists():
            lock = {s.repo: resolve_commit(s.repo, s.ref, token=token) for s in SOURCES}
            write_lock(args.lock, lock)
            print(f"wrote {args.lock}")
        else:
            lock = read_lock(args.lock)
        missing = [s.repo for s in SOURCES if s.repo not in lock]
        if missing:
            raise FetchError(f"{args.lock} has no pin for {', '.join(missing)}; use --update-lock")
        docs = build(SOURCES, lock, token=token)
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    n = write_jsonl(docs, args.out)
    words = sorted(p.words for d in docs for p in d.passages)
    print(
        f"{len(docs)} documents, {n} passages -> {args.out}\n"
        f"words per passage: min {words[0]}, median {words[len(words) // 2]}, max {words[-1]}"
    )
    return 0
