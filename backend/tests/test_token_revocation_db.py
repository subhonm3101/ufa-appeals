"""Отзыв токенов: выход, смена пароля, отключение (шаг 12.1). Нужна тестовая база."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

PASSWORD = "Xk9#mQ2$vLp7wZ"
NEW_PASSWORD = "Qw8#nT4$rBz6yH"
BODY = "Во дворе дома не работает освещение уже две недели."


@pytest.fixture
def client():
    from app.api import public, register
    from app.main import app
    for lim in (register.register_limiter, public.submit_limiter):
        lim.reset()
    yield TestClient(app)
    for lim in (register.register_limiter, public.submit_limiter):
        lim.reset()


@pytest.fixture
def engine():
    from app.db import engine
    return engine


@pytest.fixture
def citizen(client, engine):
    email = f"pytest_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    uid = r.json()["user"]["id"]
    yield {"id": uid, "email": email, "token": r.json()["access_token"]}
    with engine.begin() as c:
        c.execute(text("DELETE FROM appeals WHERE citizen_id = :u"), {"u": uid})
        c.execute(text("DELETE FROM audit_log WHERE user_id = :u OR details->>'email' = :e"), {"u": uid, "e": email})
        c.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})


def h(token):
    return {"Authorization": f"Bearer {token}"}


def login(client, email, password):
    r = client.post("/api/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_logout_revokes_token_but_login_works_again(client, citizen):
    assert client.get("/api/auth/me", headers=h(citizen["token"])).status_code == 200
    assert client.post("/api/auth/logout", headers=h(citizen["token"])).status_code == 204
    assert client.get("/api/auth/me", headers=h(citizen["token"])).status_code == 401
    fresh = login(client, citizen["email"], PASSWORD)
    assert client.get("/api/auth/me", headers=h(fresh)).status_code == 200


def test_logout_revokes_all_sessions_of_the_user(client, citizen):
    second = login(client, citizen["email"], PASSWORD)
    client.post("/api/auth/logout", headers=h(citizen["token"]))
    assert client.get("/api/auth/me", headers=h(second)).status_code == 401


def test_other_users_tokens_survive_logout(client, citizen, make_user):
    staff = make_user("operator")
    client.post("/api/auth/logout", headers=h(citizen["token"]))
    assert client.get("/api/auth/me", headers=staff.headers).status_code == 200


def test_password_change_revokes_old_tokens(client, citizen):
    r = client.post(
        "/api/auth/change-password", headers=h(citizen["token"]),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 204, r.text
    assert client.get("/api/auth/me", headers=h(citizen["token"])).status_code == 401
    fresh = login(client, citizen["email"], NEW_PASSWORD)
    assert client.get("/api/auth/me", headers=h(fresh)).status_code == 200


def test_deactivation_revokes_token_even_after_reactivation(client, engine, citizen):
    with engine.begin() as c:
        c.execute(text("UPDATE users SET is_active = FALSE WHERE id = :u"), {"u": citizen["id"]})
    assert client.get("/api/auth/me", headers=h(citizen["token"])).status_code == 401
    with engine.begin() as c:
        c.execute(text("UPDATE users SET is_active = TRUE WHERE id = :u"), {"u": citizen["id"]})
    assert client.get("/api/auth/me", headers=h(citizen["token"])).status_code == 401


def test_revoked_token_does_not_link_public_submission(client, engine, citizen):
    client.post("/api/auth/logout", headers=h(citizen["token"]))
    r = client.post("/api/public/appeals", data={"text": BODY}, headers=h(citizen["token"]))
    assert r.status_code == 201, r.text
    with engine.begin() as c:
        owner = c.execute(
            text("SELECT citizen_id FROM appeals WHERE public_number = :n"), {"n": r.json()["public_number"]}
        ).scalar_one()
        c.execute(text("DELETE FROM appeals WHERE public_number = :n"), {"n": r.json()["public_number"]})
    assert owner is None
