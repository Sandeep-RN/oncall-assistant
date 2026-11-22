"""The daily LLM budget (ADR 0003, point 5).

The provider's free tier allows a fixed number of tokens a day for everyone together. Public
visitors may use PUBLIC_SHARE_PCT of it; a demo-token holder may use whatever is left of the total.
The count is in TOKENS, not calls, because tokens run out first (about 2.2K per answer against
200K a day, while requests are limited at 1K a day).

The window is a UTC calendar day. That is an approximation: checked 2026-11-23, Groq documents no
reset time for its daily token limit, and its daily-request header is a countdown, so its window
looks rolling. The provider's own 429 stays the hard stop, and a 429 already becomes a saved answer.

The check is "used so far < limit", so the answer that crosses the line is the last one allowed:
overshoot is bounded by the answers in flight (at most two) and by one answer's size.

Errors from the ledger are NOT caught here: what a broken ledger means is the service's decision.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

PUBLIC = "public"
# The ConfigMap's values (gitops apps/oncall-assistant/base/configmap.yaml); also the defaults.
DEFAULT_TOTAL = 200_000
DEFAULT_PUBLIC_PCT = 70
_DIGITS = re.compile(r"[0-9]+")


class BudgetConfigError(ValueError):
    """A budget setting is not a valid number. Never replaced by a default: a typo would hide."""


class Ledger(Protocol):
    def used(self, day: date) -> dict[str, int]:
        """Tokens used so far on this day, per caller ("public" or a token's name)."""

    def add(self, day: date, who: str, tokens: int) -> None:
        """Add one answer's tokens to this caller's count for this day."""


def _integer(name: str, raw: str, low: int, high: int | None = None) -> int:
    if not _DIGITS.fullmatch(raw):
        raise BudgetConfigError(f"{name} must be a whole number, got {raw!r}")
    value = int(raw)
    if value < low or (high is not None and value > high):
        bound = f"at least {low}" if high is None else f"from {low} to {high}"
        raise BudgetConfigError(f"{name} must be {bound}, got {value}")
    return value


@dataclass(frozen=True)
class BudgetSettings:
    total: int = DEFAULT_TOTAL
    public_pct: int = DEFAULT_PUBLIC_PCT

    @property
    def public_limit(self) -> int:
        return self.total * self.public_pct // 100

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BudgetSettings:
        env = os.environ if env is None else env
        total, pct = DEFAULT_TOTAL, DEFAULT_PUBLIC_PCT
        if "DAILY_TOKENS_TOTAL" in env:
            total = _integer("DAILY_TOKENS_TOTAL", env["DAILY_TOKENS_TOTAL"], 1)
        if "PUBLIC_SHARE_PCT" in env:
            pct = _integer("PUBLIC_SHARE_PCT", env["PUBLIC_SHARE_PCT"], 1, 100)
        return cls(total, pct)


def utc_today() -> date:
    return datetime.now(UTC).date()


class Budget:
    def __init__(
        self, ledger: Ledger, settings: BudgetSettings, today: Callable[[], date] = utc_today
    ):
        self.ledger, self.settings, self.today = ledger, settings, today

    def allows(self, who: str) -> bool:
        """May this caller have one more live answer today?"""
        used = self.ledger.used(self.today())
        public = used.get(PUBLIC, 0)
        if who == PUBLIC:
            return public < self.settings.public_limit
        # A token holder draws on what is left of the day's total, after the public's use and
        # every token's use. The public's own share is not reduced by token use.
        return sum(used.values()) < self.settings.total

    def record(self, who: str, tokens: int) -> None:
        self.ledger.add(self.today(), who, tokens)
