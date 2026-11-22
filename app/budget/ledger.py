"""The ledger in Postgres: one row per (day, caller) in llm_usage (ADR 0003, point 6).

The app's database role is read-only by default (platform repo, roles.sql:
default_transaction_read_only = on) and may write exactly this table. A write therefore opts in, per
transaction, with
`SET TRANSACTION READ WRITE` as the FIRST statement; the permission ends with the transaction, so a
pooled connection that is reused is read-only again. Any other write path still fails, which is the
point of keeping the default on.

Counts are added with one atomic upsert, so two answers finishing together lose nothing. Errors are
left to the caller: UndefinedTable and InsufficientPrivilege mean the ledger itself is broken,
OperationalError means the database is unreachable, and the service treats those differently.
"""

from __future__ import annotations

from datetime import date


class PgLedger:
    def __init__(self, pool):
        self.pool = pool

    def used(self, day: date) -> dict[str, int]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT who, tokens FROM llm_usage WHERE day = %s", (day,)
            ).fetchall()
        return {who: int(tokens) for who, tokens in rows}

    def add(self, day: date, who: str, tokens: int) -> None:
        if tokens < 0:
            raise ValueError("a token count cannot be negative")
        with self.pool.connection() as conn:
            conn.execute("SET TRANSACTION READ WRITE")  # first statement, or Postgres refuses it
            conn.execute(
                "INSERT INTO llm_usage (day, who, tokens, calls) VALUES (%s, %s, %s, 1)"
                " ON CONFLICT (day, who) DO UPDATE"
                " SET tokens = llm_usage.tokens + EXCLUDED.tokens, calls = llm_usage.calls + 1",
                (day, who, tokens),
            )
