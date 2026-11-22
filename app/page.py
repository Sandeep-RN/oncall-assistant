"""The page: one static HTML file served at GET / (issue #6).

The file has one inline <script> and one inline <style>, and the response carries a
Content-Security-Policy that allows exactly those two blocks (by their SHA-256) and nothing else.
So even if a bug ever let model text become markup, the browser would refuse to run it, and the
page can talk only to its own origin. The hashes are computed from the file at startup, so editing
the page never needs a second edit to a header.

A missing page file is a broken build, not a missing dependency: it fails at import, loudly, and the
image smoke test in CI catches it. That is different from /ask's database or provider, whose
absence must never stop the pod (ADR 0016 in the platform repo).
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PAGE_FILE = Path(__file__).parent / "static" / "index.html"

# (tag, body) of every inline <script> and <style>. The body is exactly the bytes the browser
# hashes, so it is captured without trimming.
INLINE_BLOCKS = re.compile(r"<(script|style)(?:\s[^>]*)?>(.*?)</\1>", re.DOTALL)


@dataclass(frozen=True)
class Page:
    html: str
    headers: dict[str, str]


def _source(body: str) -> str:
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    return f"'sha256-{digest}'"


def content_security_policy(html: str) -> str:
    sources: dict[str, list[str]] = {"script": [], "style": []}
    for tag, body in INLINE_BLOCKS.findall(html):
        sources[tag].append(_source(body))
    return "; ".join(
        [
            "default-src 'none'",
            # An empty list means "no script at all", which is what 'none' says.
            "script-src " + (" ".join(sources["script"]) or "'none'"),
            "style-src " + (" ".join(sources["style"]) or "'none'"),
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ]
    )


def load_page(path: Path = PAGE_FILE) -> Page:
    html = path.read_text(encoding="utf-8")
    return Page(
        html,
        {
            "Content-Security-Policy": content_security_policy(html),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            # Revalidate on every load: a deploy must show up at once (the file is a few KB).
            "Cache-Control": "no-cache",
        },
    )
