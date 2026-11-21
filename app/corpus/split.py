"""Split one Markdown document into passages that can be retrieved and cited alone.

Rules (tuned against the eval set later, issue #8):
- A new section starts at a heading of level 1 to 3. Deeper headings stay in the text.
- Lines inside fenced code blocks are never headings: runbooks are full of `# comment` lines.
- A long section is cut between blocks (paragraphs, whole fences, whole tables), never inside one.
  A single block larger than the limit stays whole rather than being cut mid-command.
- A section shorter than `min_words` is carried into the next one, so a passage is never just a
  title. The carried text is then cited under the next section's anchor (same document).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace

MAX_WORDS = 350
MIN_WORDS = 40
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


@dataclass(frozen=True)
class Passage:
    repo: str  # "owner/name"
    path: str
    heading_path: tuple[str, ...]
    anchor: str  # GitHub heading anchor of the passage's own heading
    commit: str
    text: str
    ordinal: int  # position within the document, 0-based
    words: int

    @property
    def url(self) -> str:
        # A permalink at the pinned commit: the cited text cannot drift under the link.
        base = f"https://github.com/{self.repo}/blob/{self.commit}/{self.path}"
        return f"{base}#{self.anchor}" if self.anchor else base

    @property
    def id(self) -> str:
        # Stable across runs: the same document and heading give the same id.
        key = f"{self.repo}|{self.path}|{self.anchor}|{self.ordinal}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]


def github_slug(heading: str) -> str:
    """The anchor GitHub gives a heading (without the -1, -2 suffix for duplicates)."""
    text = _LINK.sub(r"\1", heading)
    # Drop inline-markup characters. `_` is kept: GitHub keeps it in anchors.
    text = re.sub(r"[`*~]", "", text)
    text = re.sub(r"[^\w\- ]", "", text.lower())
    return text.strip().replace(" ", "-")


def _words(text: str) -> int:
    return len(text.split())


def _sections(text: str):
    """Yield (level, heading, body_lines) for every section; level 0 = text before any heading."""
    level, heading, body, in_fence = 0, "", [], False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m and len(m.group(1)) <= 3:
            yield level, heading, body
            level, heading, body = len(m.group(1)), m.group(2), []
        else:
            body.append(line)
    yield level, heading, body


def _blocks(lines: list[str]) -> list[str]:
    """Group lines into blocks separated by blank lines; a fenced block is one block."""
    blocks, cur, in_fence = [], [], False
    for line in lines:
        if _FENCE.match(line):
            in_fence = not in_fence
        if not line.strip() and not in_fence:
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def _is_atomic(block: str) -> bool:
    """Fenced code and tables are never cut: half a command or a headerless table misleads."""
    return bool(_FENCE.match(block)) or block.lstrip().startswith("|")


def _cut_lines(block: str, max_words: int) -> list[str]:
    """Cut a long plain block (a long list, say) at line boundaries."""
    pieces, cur, size = [], [], 0
    for line in block.splitlines():
        w = _words(line)
        if cur and size + w > max_words:
            pieces.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += w
    if cur:
        pieces.append("\n".join(cur))
    return pieces


def _pack(blocks: list[str], max_words: int, min_words: int = MIN_WORDS) -> list[str]:
    units: list[str] = []
    for block in blocks:
        if _words(block) > max_words and not _is_atomic(block):
            units.extend(_cut_lines(block, max_words))
        else:
            units.append(block)
    chunks, cur, size = [], [], 0
    for unit in units:
        w = _words(unit)
        # A short lead-in (one sentence before a big table) stays with what follows it.
        if cur and size + w > max_words and size >= min_words:
            chunks.append("\n\n".join(cur))
            cur, size = [], 0
        cur.append(unit)
        size += w
    if cur:
        chunks.append("\n\n".join(cur))
    # A short closing chunk (often a sentence after a table that filled the last one) would
    # be a useless passage on its own: attach it to the one before.
    if len(chunks) > 1 and _words(chunks[-1]) < min_words:
        tail = chunks.pop()
        chunks[-1] += "\n\n" + tail
    return chunks


def split_markdown(
    text: str,
    *,
    repo: str,
    path: str,
    commit: str,
    max_words: int = MAX_WORDS,
    min_words: int = MIN_WORDS,
) -> list[Passage]:
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    # (heading_path, anchor, blocks) per section, in document order
    sections: list[tuple[tuple[str, ...], str, list[str]]] = []
    for level, heading, body in _sections(text):
        anchor = ""
        if level:
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
            slug = github_slug(heading)
            n = seen.get(slug, 0)
            seen[slug] = n + 1
            anchor = slug if n == 0 else f"{slug}-{n}"
        blocks = _blocks(body)
        if blocks or level:
            sections.append((tuple(h for _, h in stack), anchor, blocks))

    passages: list[Passage] = []
    carry: list[str] = []  # blocks of tiny sections waiting for the next section

    def emit(path_, anchor, chunk_blocks):
        for chunk in _pack(chunk_blocks, max_words, min_words):
            passages.append(
                Passage(repo, path, path_, anchor, commit, chunk, len(passages), _words(chunk))
            )

    for heading_path, anchor, blocks in sections:
        if not blocks:
            continue  # heading with no text of its own: its children carry the content
        total = sum(_words(b) for b in blocks) + sum(_words(b) for b in carry)
        if total < min_words:
            # Keep the tiny section's title in the text so its words still have context.
            if heading_path:
                carry.append(f"{'#' * len(heading_path)} {heading_path[-1]}")
            carry.extend(blocks)
            continue
        emit(heading_path, anchor, [*carry, *blocks])
        carry = []
    if carry:
        # Only a short tail is left (the carry never reaches min_words on its own).
        if passages:
            last = passages[-1]
            merged = last.text + "\n\n" + "\n\n".join(carry)
            passages[-1] = replace(last, text=merged, words=_words(merged))
        else:
            emit(sections[-1][0], sections[-1][1], carry)
    return passages
