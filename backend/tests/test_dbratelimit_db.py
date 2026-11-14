"""Ограничитель запросов в базе (шаг 12.3). Нужна тестовая база."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app.services.ratelimit import DbRateLimiter

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)


@pytest.fixture
def limiter():
    from app.db import engine
    lim = DbRateLimiter(f"pytest-{uuid.uuid4().hex[:8]}", limit=3, window=60)
    yield lim
    with engine.begin() as c:
        c.execute(text("DELETE FROM rate_hits WHERE bucket = :b"), {"b": lim.name})


def test_limit_per_key(limiter):
    assert [limiter.allow("a") for _ in range(4)] == [True, True, True, False]
    assert limiter.allow("b")


def test_buckets_are_independent(limiter):
    other = DbRateLimiter(limiter.name + "-x", limit=1, window=60)
    try:
        assert other.allow("a") and not other.allow("a")
        assert limiter.allow("a")
    finally:
        other.reset()


def test_window_expires(limiter):
    from app.db import engine
    for _ in range(3):
        assert limiter.allow("a")
    assert not limiter.allow("a")
    with engine.begin() as c:
        c.execute(
            text("UPDATE rate_hits SET at = at - interval '2 minutes' WHERE bucket = :b"), {"b": limiter.name}
        )
    assert limiter.allow("a")


def test_reset(limiter):
    for _ in range(3):
        limiter.allow("a")
    assert not limiter.allow("a")
    limiter.reset()
    assert limiter.allow("a")


def test_state_survives_new_instance(limiter):
    for _ in range(3):
        limiter.allow("a")
    same = DbRateLimiter(limiter.name, limit=3, window=60)
    assert not same.allow("a")


def test_parallel_requests_cannot_exceed_limit(limiter):
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: limiter.allow("burst"), range(24)))
    assert results.count(True) == 3


def test_missing_ip_key_works(limiter):
    assert limiter.allow(None)
