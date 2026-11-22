"""The daily LLM budget's rules (ADR 0003, points 5 and 7), with an in-memory ledger.

The rules: tokens, not calls. Public visitors may use PUBLIC_SHARE_PCT of DAILY_TOKENS_TOTAL; a
demo-token holder may use whatever is left of the total. A UTC day is the window. The check is
"used so far < limit", so the answer that crosses the line is the last one: overshoot is bounded
by the answers in flight, and the provider's own 429 is the hard stop.
"""

from datetime import date

import pytest

from app.budget.budget import PUBLIC, Budget, BudgetConfigError, BudgetSettings

DAY = date(2026, 11, 23)


class FakeLedger:
    def __init__(self):
        self.rows: dict[tuple[date, str], int] = {}

    def used(self, day):
        return {who: tokens for (d, who), tokens in self.rows.items() if d == day}

    def add(self, day, who, tokens):
        self.rows[(day, who)] = self.rows.get((day, who), 0) + tokens


def budget(total=1000, pct=70, ledger=None, today=lambda: DAY):
    return Budget(ledger or FakeLedger(), BudgetSettings(total, pct), today=today)


# --- settings -----------------------------------------------------------------------------------


def test_the_defaults_are_the_ones_in_the_config_map():
    s = BudgetSettings.from_env({})
    assert (s.total, s.public_pct, s.public_limit) == (200_000, 70, 140_000)


def test_the_settings_come_from_the_environment():
    s = BudgetSettings.from_env({"DAILY_TOKENS_TOTAL": "50000", "PUBLIC_SHARE_PCT": "40"})
    assert (s.total, s.public_limit) == (50_000, 20_000)


@pytest.mark.parametrize(
    "env",
    [
        {"DAILY_TOKENS_TOTAL": "abc"},
        {"DAILY_TOKENS_TOTAL": "0"},
        {"DAILY_TOKENS_TOTAL": "-5"},
        {"DAILY_TOKENS_TOTAL": "200K"},
        {"PUBLIC_SHARE_PCT": "0"},
        {"PUBLIC_SHARE_PCT": "101"},
        {"PUBLIC_SHARE_PCT": "seventy"},
        {"PUBLIC_SHARE_PCT": ""},
    ],
)
def test_a_bad_setting_is_refused_not_silently_replaced(env):
    # CI checks the same rules on the ConfigMap; here a bad value must not become a default.
    with pytest.raises(BudgetConfigError):
        BudgetSettings.from_env(env)


# --- who may ask --------------------------------------------------------------------------------


def test_the_public_may_ask_until_its_share_is_used():
    b = budget(total=1000, pct=70)  # public limit 700
    assert b.allows(PUBLIC)
    b.record(PUBLIC, 699)
    assert b.allows(PUBLIC)  # 699 < 700: one more answer is allowed, and may cross the line
    b.record(PUBLIC, 2)
    assert not b.allows(PUBLIC)  # 701 >= 700


def test_exactly_at_the_limit_is_spent():
    b = budget(total=1000, pct=70)
    b.record(PUBLIC, 700)
    assert not b.allows(PUBLIC)


def test_a_token_holder_may_use_what_the_public_cannot():
    b = budget(total=1000, pct=70)
    b.record(PUBLIC, 900)  # the public share is long gone
    assert not b.allows(PUBLIC)
    assert b.allows("owner")


def test_a_token_holder_stops_at_the_total_not_before():
    b = budget(total=1000, pct=70)
    b.record(PUBLIC, 700)
    b.record("owner", 299)
    assert b.allows("owner")  # 700 + 299 = 999 < 1000
    b.record("owner", 1)
    assert not b.allows("owner")  # the day's total is used


def test_token_use_does_not_shrink_the_public_share():
    b = budget(total=1000, pct=70)
    b.record("owner", 800)
    assert b.allows(PUBLIC)  # the share is the public's own: 0 of 700 used


def test_all_tokens_draw_on_the_same_remainder():
    b = budget(total=1000, pct=70)
    b.record("owner", 500)
    b.record("reviewer", 500)
    assert not b.allows("owner") and not b.allows("reviewer")


# --- the window ---------------------------------------------------------------------------------


def test_a_new_utc_day_starts_with_a_full_budget():
    ledger = FakeLedger()
    today = [DAY]
    b = budget(ledger=ledger, today=lambda: today[0])
    b.record(PUBLIC, 5000)
    assert not b.allows(PUBLIC)
    today[0] = date(2026, 11, 24)
    assert b.allows(PUBLIC)
    b.record(PUBLIC, 10)
    assert ledger.rows[(date(2026, 11, 24), PUBLIC)] == 10
    assert ledger.rows[(DAY, PUBLIC)] == 5000  # yesterday's count is kept, not overwritten


def test_record_adds_to_the_days_row():
    ledger = FakeLedger()
    b = budget(ledger=ledger)
    b.record("owner", 100)
    b.record("owner", 50)
    assert ledger.rows == {(DAY, "owner"): 150}


def test_a_ledger_error_is_not_hidden_by_the_budget():
    # The service decides what a ledger failure means (fail open, or fail fast): the budget must
    # not swallow the error for it.
    class Broken(FakeLedger):
        def used(self, day):
            raise RuntimeError("ledger down")

    with pytest.raises(RuntimeError):
        budget(ledger=Broken()).allows(PUBLIC)
