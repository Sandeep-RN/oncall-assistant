"""Which retrieved passages the model reads (issue #74, ADR 0004).

The model gets the top K passages by similarity. When most of them come from ONE document, the
question is about that document, and the right section is often just below the cut: on the eval
set the runbook's "Triage" section ranked 10th or 11th while all of the top 5 were other sections of
the same runbook (eval A01). So when NEED of the top K share a document, up to EXTRA more sections
of that document are added from the top CANDIDATES, in rank order, after the top K.

Measured on the whole eval set, without model calls (2026-11-28): A01 found on the pinned and the
latest corpus, no other question lost, the prompt about 5% longer on average. The answerer and the
retrieval eval both call this function, so the eval scores what a visitor gets.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from app.index.store import Hit

K = 5
NEED = 4
EXTRA = 3
CANDIDATES = 20


def same_document(
    candidates: Sequence[Hit], *, k: int = K, need: int = NEED, extra: int = EXTRA
) -> list[Hit]:
    """The top `k` candidates, plus up to `extra` more from the document that holds at least
    `need` of them. `candidates` are in rank order; only the first CANDIDATES are considered."""
    pool = list(candidates[:CANDIDATES])
    top = pool[:k]
    if not top or extra <= 0:
        return top
    doc, count = Counter((h.repo, h.path) for h in top).most_common(1)[0]
    if count < need:
        return top
    more = [h for h in pool[k:] if (h.repo, h.path) == doc]
    return top + more[:extra]
