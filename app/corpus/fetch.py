"""Fetch the Markdown files of a public GitHub repo at one commit.

Only the standard library. The repo tarball is streamed to a temporary file (not held in memory)
and read member by member; nothing is extracted to disk, so a hostile archive cannot write files.
"""

from __future__ import annotations

import re
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import PurePosixPath
from typing import BinaryIO

from app.corpus.sources import Source

API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"
_SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_FILE_BYTES = 1_000_000
MAX_DOWNLOAD_BYTES = 100_000_000

Get = Callable[[str, dict[str, str]], BinaryIO]


class FetchError(RuntimeError):
    """A problem a person has to look at; the message says what to check."""


def with_retries(fn: Callable[[], object], *, attempts: int = 3, sleep=time.sleep):
    """Call fn, retrying network errors with a growing pause; raise FetchError at the end."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise FetchError(f"HTTP {e.code} from GitHub: {e.reason}") from e
            last = e
        except OSError as e:  # URLError, timeouts and resets are all OSError
            last = e
        if i < attempts - 1:
            sleep(2**i)
    raise FetchError(f"GitHub unreachable after {attempts} attempts: {last}")


def http_get(url: str, headers: dict[str, str]) -> BinaryIO:
    """The real HTTP boundary (replaced by a fake in tests). GITHUB_TOKEN is optional."""
    req = urllib.request.Request(url, headers={"User-Agent": "oncall-assistant", **headers})
    return urllib.request.urlopen(req, timeout=30)  # fixed https hosts only


def _call(get: Get, url: str, headers: dict[str, str]) -> BinaryIO:
    return with_retries(lambda: get(url, headers))  # type: ignore[return-value]


def resolve_commit(repo: str, ref: str, *, get: Get = http_get, token: str | None = None) -> str:
    headers = {"Accept": "application/vnd.github.sha"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with _call(get, f"{API}/repos/{repo}/commits/{ref}", headers) as resp:
        sha = resp.read(100).decode("ascii", "replace").strip()
    if not _SHA.match(sha):
        raise FetchError(f"{repo}@{ref}: GitHub did not return a commit SHA (rate limit?)")
    return sha


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    p = PurePosixPath(path)
    return any(p.full_match(pat) for pat in patterns)


def iter_markdown(
    source: Source,
    sha: str,
    *,
    get: Get = http_get,
    token: str | None = None,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_download_bytes: int = MAX_DOWNLOAD_BYTES,
) -> Iterator[tuple[str, str]]:
    """Yield (path, text) for each wanted file of the repo at commit `sha`."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with tempfile.TemporaryFile() as tmp:
        with _call(get, f"{CODELOAD}/{source.repo}/tar.gz/{sha}", headers) as resp:
            copied = 0
            while chunk := resp.read(1 << 20):
                copied += len(chunk)
                if copied > max_download_bytes:
                    raise FetchError(
                        f"{source.repo}: download larger than {max_download_bytes} bytes"
                    )
                tmp.write(chunk)
        tmp.seek(0)
        try:
            with tarfile.open(fileobj=tmp, mode="r:gz") as tar:
                for member in tar:
                    if not member.isfile():  # skips directories, symlinks, hard links
                        continue
                    # Drop the archive's top-level directory ("owner-repo-<sha>/").
                    parts = PurePosixPath(member.name).parts[1:]
                    if not parts or ".." in parts:
                        continue
                    path = "/".join(parts)
                    if not _matches(path, source.include) or _matches(path, source.exclude):
                        continue
                    if member.size > max_file_bytes:
                        continue
                    f = tar.extractfile(member)
                    if f is None:
                        continue
                    try:
                        yield path, f.read().decode("utf-8")
                    except UnicodeDecodeError:
                        continue  # not text: not a document
        except (tarfile.TarError, EOFError) as e:
            raise FetchError(f"{source.repo}: unreadable archive: {e}") from e
