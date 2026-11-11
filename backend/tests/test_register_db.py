"""Регистрация гражданина и его права. Нужна тестовая база."""
import os
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

PASSWORD = "Xk9#mQ2$vLp7wZ"
OPEN_PREFIXES = ("/api/auth/", "/api/public/", "/api/my/", "/api/notifications")


@pytest.fixture
def client():
    from app.api import register
    from app.main import app

    register.register_limiter.reset()
    yield TestClient(app)
    register.register_limiter.reset()


@pytest.fixture
def emails():
    items = []
    yield items
    from app.db import engine
    with engine.begin() as c:
        for e in items:
            c.execute(text("DELETE FROM audit_log WHERE user_id IN (SELECT id FROM users WHERE lower(email) = :e)"), {"e": e})
            c.execute(text("DELETE FROM users WHERE lower(email) = :e"), {"e": e})


def new_email():
    return f"pytest_{uuid.uuid4().hex[:10]}@example.com"


def register(client, emails, email=None, password=PASSWORD, **extra):
    email = new_email() if email is None else email
    r = client.post("/api/auth/register", json={"email": email, "password": password, **extra})
    if r.status_code == 201:
        emails.append(email.strip().lower())
    return r


def test_register_returns_working_token(client, emails):
    r = register(client, emails, full_name="  Иван   Петров ")
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["role"] == "citizen" and body["user"]["full_name"] == "Иван Петров"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["role"] == "citizen"


def test_registered_citizen_can_log_in(client, emails):
    email = new_email()
    assert register(client, emails, email=email).status_code == 201
    r = client.post("/api/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["role"] == "citizen"


@pytest.mark.parametrize("password", ["short1", "onlyletters", "12345678", "a" * 129 + "1"])
def test_weak_password_rejected(client, emails, password):
    assert register(client, emails, password=password).status_code == 422


@pytest.mark.parametrize("email", ["abc", "a@b", "a b@c.ru", ""])
def test_bad_email_rejected(client, emails, email):
    assert register(client, emails, email=email).status_code == 422


def test_duplicate_email_rejected_case_insensitive(client, emails):
    email = new_email()
    assert register(client, emails, email=email).status_code == 201
    assert register(client, emails, email=email.upper()).status_code == 409


def test_registration_is_rate_limited(client, emails):
    for _ in range(5):
        assert register(client, emails).status_code == 201
    assert register(client, emails).status_code == 429


def test_citizen_cannot_create_staff_accounts_via_register(client, emails):
    r = register(client, emails, role="admin")
    assert r.status_code == 201 and r.json()["user"]["role"] == "citizen"


def test_citizen_is_denied_on_every_staff_route(client, emails):
    token = register(client, emails).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    from app.main import app

    checked, open_routes = 0, []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if not path.startswith("/api/") or path.startswith(OPEN_PREFIXES) or not methods:
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        for method in methods - {"HEAD", "OPTIONS"}:
            r = client.request(method, url, headers=headers)
            if r.status_code != 403:
                open_routes.append(f"{method} {path} -> {r.status_code}")
            checked += 1
    assert not open_routes, "гражданину доступны служебные маршруты: " + "; ".join(open_routes)
    assert checked > 20
