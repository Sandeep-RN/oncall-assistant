"""A database that is down must answer 503 quickly, not after the pool's default 30 s (issue #6).

Found on 2026-11-22 while writing #18: a pool timeout is also a psycopg error, so it was caught
and became a clean 503 "index_unavailable", but only after the default wait, far over the 8 s
latency target. No database is needed here: the pool points at a port where nothing listens.
"""

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.answer.service import Answerer
from app.main import DB_POOL_TIMEOUT, app, open_pool, pool_search

DEAD = "host=127.0.0.1 port=1 dbname=none connect_timeout=1"


class FakeEmbedder:
    def embed_query(self, text):
        return np.zeros(384, dtype=np.float32)


@pytest.fixture
def dead_pool():
    pool = open_pool(DEAD, timeout=1.0)
    yield pool
    pool.close(timeout=2)
    app.state.answerer = None


def never_called(messages):
    raise AssertionError("no model call without passages")


def test_the_default_wait_fits_inside_the_latency_target():
    # The target is 8 s for a live answer; embedding takes ~0.1 s, so the wait must stay short.
    assert 0 < DB_POOL_TIMEOUT <= 3


def test_a_dead_database_answers_503_within_the_pool_timeout(dead_pool):
    app.state.answerer = Answerer(FakeEmbedder(), pool_search(dead_pool), never_called, model="m")
    started = time.perf_counter()
    r = TestClient(app).post("/ask", json={"question": "is the database up?"})
    elapsed = time.perf_counter() - started
    assert r.status_code == 503
    assert r.json()["kind"] == "unavailable" and r.json()["reason"] == "index_unavailable"
    # 1 s pool timeout in this test; the default 30 s wait would fail this by a mile.
    assert elapsed < 4, f"took {elapsed:.1f} s"


def test_the_slot_is_released_after_a_pool_timeout(dead_pool):
    a = Answerer(FakeEmbedder(), pool_search(dead_pool), never_called, model="m", max_concurrent=1)
    app.state.answerer = a
    api = TestClient(app)
    for _ in range(2):  # a leaked slot would turn the second answer into "busy"
        assert api.post("/ask", json={"question": "again please"}).json()["reason"] == (
            "index_unavailable"
        )
