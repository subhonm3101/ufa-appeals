"""Тесты пересчёта приоритетов: журнал, идемпотентность, права, будущая дата."""
import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

URL = "/api/priority/recalculate"
TEST_DATE = "2000-01-01"  # изолированная дата, чтобы не задеть реальные снимки


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_snapshot():
    yield
    from sqlalchemy import text

    from app.db import engine
    with engine.begin() as c:
        c.execute(text("DELETE FROM priority_scores WHERE as_of = '2000-01-01 23:59:59+00'"))


def _snapshot_rows():
    from sqlalchemy import text

    from app.db import engine
    with engine.connect() as c:
        return c.execute(text(
            "SELECT count(*) FROM priority_scores WHERE as_of = '2000-01-01 23:59:59+00'"
        )).scalar_one()


def test_analyst_cannot_recalculate(client, make_user):
    user = make_user("analyst")
    assert client.post(URL, headers=user.headers).status_code == 403


def test_future_date_rejected(client, make_user):
    user = make_user("manager")
    r = client.post(URL, params={"as_of": "2999-01-01"}, headers=user.headers)
    assert r.status_code == 422


def test_snapshot_time_is_fixed(client, make_user):
    user = make_user("manager")
    r = client.post(URL, params={"as_of": TEST_DATE}, headers=user.headers)
    assert r.status_code == 200
    assert r.json()["as_of"].startswith("2000-01-01T23:59:59")


def test_recalculate_is_written_to_audit_log(client, make_user):
    from sqlalchemy import text

    from app.db import engine
    user = make_user("manager")
    r = client.post(URL, params={"as_of": TEST_DATE}, headers=user.headers)
    assert r.status_code == 200
    with engine.connect() as c:
        n = c.execute(text(
            "SELECT count(*) FROM audit_log WHERE user_id = :u AND action = 'priority_recalculate'"
        ), {"u": user.id}).scalar_one()
    assert n == 1


def test_repeated_recalculate_does_not_duplicate_snapshot(client, make_user):
    user = make_user("admin")
    assert client.post(URL, params={"as_of": TEST_DATE}, headers=user.headers).status_code == 200
    first = _snapshot_rows()
    assert client.post(URL, params={"as_of": TEST_DATE}, headers=user.headers).status_code == 200
    assert _snapshot_rows() == first
