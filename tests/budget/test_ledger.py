"""The ledger against a REAL Postgres, as a role like the app's (ADR 0003, point 6).

The app role is read-only by default and may write only the ledger, only inside an explicit
`SET TRANSACTION READ WRITE`. These tests create a role with the same setting and the same grants
(platform repo, apps/oncall-assistant/base/sql/roles.sql, demo #207), so a write that forgets to
opt in fails here exactly as it would in the cluster. The table definition below is a copy of the
one in roles.sql: keep the two in step.
"""

import os
import threading
from datetime import date

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.budget.ledger import PgLedger

DAY = date(2026, 11, 23)
ROLE = "ledger_test_app"
DDL = """
CREATE TABLE IF NOT EXISTS public.llm_usage (
  day    date    NOT NULL,
  who    text    NOT NULL CHECK (char_length(who) BETWEEN 1 AND 64),
  tokens bigint  NOT NULL DEFAULT 0 CHECK (tokens >= 0),
  calls  integer NOT NULL DEFAULT 0 CHECK (calls >= 0),
  PRIMARY KEY (day, who)
)
"""


def admin():
    return psycopg.connect("", autocommit=True)


@pytest.fixture
def pool():
    if "PGHOST" not in os.environ:
        pytest.skip("needs Postgres (PGHOST)")
    with admin() as c:
        c.execute("DROP TABLE IF EXISTS public.llm_usage")
        c.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') "
            f"THEN CREATE ROLE {ROLE} LOGIN; END IF; END $$"
        )
        c.execute(f"ALTER ROLE {ROLE} SET default_transaction_read_only = on")
        c.execute(DDL)
        c.execute(f"GRANT SELECT, INSERT, UPDATE ON public.llm_usage TO {ROLE}")
    # One connection, so every call reuses it: a permission that leaked from one transaction to the
    # next would show up in the test below.
    p = ConnectionPool("", kwargs={"user": ROLE}, min_size=1, max_size=1, timeout=5, open=True)
    yield p
    p.close()
    with admin() as c:
        c.execute("DROP TABLE IF EXISTS public.llm_usage")
        c.execute(f"DROP ROLE IF EXISTS {ROLE}")


def rows():
    with admin() as c:
        return c.execute("SELECT who, tokens, calls FROM llm_usage ORDER BY who").fetchall()


def test_the_test_role_is_really_read_only(pool):
    # The premise of everything below: without opting in, this role cannot write the ledger.
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO llm_usage (day, who, tokens, calls) VALUES (%s, 'x', 1, 1)", (DAY,)
            )


def test_adds_accumulate_per_day_and_caller(pool):
    ledger = PgLedger(pool)
    ledger.add(DAY, "public", 100)
    ledger.add(DAY, "public", 50)
    ledger.add(DAY, "owner", 7)
    ledger.add(date(2026, 11, 24), "public", 3)
    assert ledger.used(DAY) == {"public": 150, "owner": 7}
    assert ledger.used(date(2026, 11, 24)) == {"public": 3}
    assert ledger.used(date(2026, 11, 25)) == {}


def test_every_add_counts_a_call(pool):
    ledger = PgLedger(pool)
    ledger.add(DAY, "public", 100)
    ledger.add(DAY, "public", 50)
    assert rows() == [("public", 150, 2)]


def test_the_write_permission_does_not_leak_to_the_next_transaction(pool):
    PgLedger(pool).add(DAY, "public", 10)
    # The same single connection is now reused: it must be read-only again.
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO llm_usage (day, who, tokens, calls) VALUES (%s, 'leak', 1, 1)", (DAY,)
            )
    assert rows() == [("public", 10, 1)]


def test_concurrent_adds_are_not_lost(pool):
    ledger = PgLedger(pool)
    errors = []

    def work():
        try:
            for _ in range(25):
                ledger.add(DAY, "public", 1)
        except Exception as e:  # noqa: BLE001 - reported below
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert rows() == [("public", 200, 200)]  # one atomic upsert per add: nothing lost


def test_a_negative_count_is_refused_before_it_reaches_the_database(pool):
    with pytest.raises(ValueError):
        PgLedger(pool).add(DAY, "public", -1)
    assert rows() == []


def test_a_missing_table_is_an_error_the_caller_can_tell_apart(pool):
    with admin() as c:
        c.execute("DROP TABLE public.llm_usage")
    ledger = PgLedger(pool)
    with pytest.raises(psycopg.errors.UndefinedTable):
        ledger.used(DAY)
    with pytest.raises(psycopg.errors.UndefinedTable):
        ledger.add(DAY, "public", 1)
