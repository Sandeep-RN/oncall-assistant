"""Fetch the pinned model files once, checked by sha256 (ADR 0001).

    python -m app.embed.download [--dir models/bge-small-en-v1.5]

Safe to re-run: a file already present with the right hash is left alone. A download goes to a
temporary name and is renamed only after its hash matches, so a broken download never looks done.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from app.corpus.fetch import FetchError, Get, http_get, with_retries
from app.embed.model import DEFAULT_DIR, FILES, MODEL_ID, REVISION

HF = "https://huggingface.co"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def download(
    model_dir: Path = DEFAULT_DIR,
    *,
    get: Get = http_get,
    files: dict[str, tuple[str, str]] = FILES,
) -> list[str]:
    """Return the names of the files that were downloaded (empty when all were present)."""
    model_dir.mkdir(parents=True, exist_ok=True)
    fetched = []
    for name, (repo_path, expected) in files.items():
        target = model_dir / name
        if target.is_file() and sha256_of(target) == expected:
            continue
        url = f"{HF}/{MODEL_ID}/resolve/{REVISION}/{repo_path}"
        tmp = target.with_name(name + ".part")
        h = hashlib.sha256()
        with with_retries(lambda u=url: get(u, {})) as resp, tmp.open("wb") as f:
            while chunk := resp.read(1 << 20):
                h.update(chunk)
                f.write(chunk)
        if h.hexdigest() != expected:
            tmp.unlink(missing_ok=True)
            raise FetchError(f"{name}: sha256 {h.hexdigest()} does not match the pinned {expected}")
        os.replace(tmp, target)
        fetched.append(name)
    return fetched


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.embed.download")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    args = ap.parse_args(argv)
    try:
        fetched = download(args.dir)
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"{args.dir}: " + (f"downloaded {', '.join(fetched)}" if fetched else "already present"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
