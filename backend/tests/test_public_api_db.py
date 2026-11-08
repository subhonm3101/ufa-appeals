"""Публичный API приёма обращений. Нужна тестовая база."""
import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

BODY = "Во дворе дома не работает освещение уже две недели."


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.api import public
    from app.main import app

    public.submit_limiter.reset()
    public.lookup_limiter.reset()
    yield TestClient(app)
    public.submit_limiter.reset()
    public.lookup_limiter.reset()


@pytest.fixture
def cleanup():
    numbers = []
    yield numbers
    from app.db import engine
    with engine.begin() as c:
        for n in numbers:
            c.execute(text("DELETE FROM appeals WHERE public_number = :n"), {"n": n})


def test_submit_without_login_returns_number(client, cleanup):
    r = client.post("/api/public/appeals", json={"text": BODY, "contact_email": "a@b.ru"})
    assert r.status_code == 201
    number = r.json()["public_number"]
    cleanup.append(number)
    assert number.startswith("UFA-")


def test_bad_text_gives_422_with_message(client):
    r = client.post("/api/public/appeals", json={"text": "мало"})
    assert r.status_code == 422
    assert "минимум" in r.json()["detail"]


def test_status_lookup_hides_private_data(client, cleanup):
    number = client.post(
        "/api/public/appeals", json={"text": BODY, "contact_email": "secret@b.ru", "address_text": "ул. Ленина, 1"}
    ).json()["public_number"]
    cleanup.append(number)
    r = client.get(f"/api/public/appeals/{number.lower()}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "new" and body["status_label"] == "Зарегистрировано"
    assert body["response_text"] is None
    assert "secret@b.ru" not in r.text and "Ленина" not in r.text and BODY not in r.text


@pytest.mark.parametrize("number", ["UFA-2026-999999", "abc", "UFA-26-1"])
def test_unknown_number_is_404(client, number):
    assert client.get(f"/api/public/appeals/{number}").status_code == 404


def test_submit_is_rate_limited(client, cleanup):
    for _ in range(5):
        r = client.post("/api/public/appeals", json={"text": BODY})
        assert r.status_code == 201
        cleanup.append(r.json()["public_number"])
    assert client.post("/api/public/appeals", json={"text": BODY}).status_code == 429


def test_districts_list(client):
    r = client.get("/api/public/districts")
    assert r.status_code == 200 and isinstance(r.json(), list)
