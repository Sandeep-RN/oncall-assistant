"""Characters a model writes that LOOK like ASCII but break a copy-paste into a shell or a search.

Found 2026-11-22 while drafting the saved answers, and confirmed in a live answer on 2026-11-23
(issue #39): gpt-oss-120b wrote a file path with U+2011 non-breaking hyphens, which is invisible on
screen and, pasted into a terminal, names a file that does not exist. For an on-call tool the answer
is only as good as what happens when it is pasted, so every answer, live or saved, goes through
`clean`.

Only characters with an exact ASCII equivalent are replaced. En and em dashes are real
punctuation in prose and are left alone. This file is deliberately ASCII only: written as
ordinals, every character is visible in review (a non-breaking hyphen looks exactly like a
hyphen).
"""

from __future__ import annotations

LOOKALIKES: dict[int, str] = {
    0x2010: "-",  # hyphen
    0x2011: "-",  # non-breaking hyphen
    0x00A0: " ",  # no-break space
    0x202F: " ",  # narrow no-break space
    0x2018: "'",  # left single quotation mark
    0x2019: "'",  # right single quotation mark (also the apostrophe)
    0x201C: '"',  # left double quotation mark
    0x201D: '"',  # right double quotation mark
}


def clean(text: str) -> str:
    return text.translate(LOOKALIKES)
