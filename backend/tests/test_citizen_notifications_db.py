"""Уведомления гражданина и сотрудников (шаг 11.4). Нужна тестовая база."""
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
BODY = "Во дворе дома не работает освещение уже две недели."


@pytest.fixture
def client():
    from app.api import my, public, register
    from app.main import app

    for limiter in (register.register_limiter, public.submit_limiter, my.comment_limiter):
        limiter.reset()
    yield TestClient(app)
    for limiter in (register.register_limiter, public.submit_limiter, my.comment_limiter):
        limiter.reset()


@pytest.fixture
def engine():
    from app.db import engine
    return engine


@pytest.fixture
def citizen(client, engine, make_user):
    email = f"pytest_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    uid = r.json()["user"]["id"]
    yield {"id": uid, "headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}
    with engine.begin() as c:
        c.execute(text("DELETE FROM appeals WHERE citizen_id = :u"), {"u": uid})
        c.execute(text("DELETE FROM appeal_comments WHERE author_id = :u"), {"u": uid})
        c.execute(text("DELETE FROM audit_log WHERE user_id = :u"), {"u": uid})
        c.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})


@pytest.fixture
def my_appeal(engine, citizen):
    with engine.begin() as c:
        row = c.execute(
            text(
                "INSERT INTO appeals (text, created_at, status, citizen_id) "
                "VALUES (:t, now(), 'new', :c) RETURNING id, public_number"
            ),
            {"t": BODY, "c": citizen["id"]},
        ).one()
    yield row.id, row.public_number
    with engine.begin() as c:
        c.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": row.id})


def feed(client, headers):
    r = client.get("/api/notifications", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_citizen_reads_own_feed_but_not_staff_routes(client, citizen):
    assert feed(client, citizen["headers"])["unread"] == 0
    assert client.get("/api/notifications/unread-count", headers=citizen["headers"]).json() == {"unread": 0}
    assert client.post("/api/notifications/read-all", headers=citizen["headers"]).status_code == 200
    assert client.get("/api/cases", headers=citizen["headers"]).status_code == 403


def test_status_change_and_public_reply_notify_citizen(client, citizen, my_appeal, make_user):
    aid, number = my_appeal
    operator = make_user("operator")
    r = client.post(f"/api/appeals/{aid}/status", json={"to_status": "accepted"}, headers=operator.headers)
    assert r.status_code == 200, r.text
    items = feed(client, citizen["headers"])["items"]
    assert any(
        n["kind"] == "appeal_update" and number in n["message"] and n["public_number"] == number
        for n in items
    )

    before = len(items)
    r = client.post(f"/api/appeals/{aid}/comments", json={"body": "внутренняя заметка"}, headers=operator.headers)
    assert r.status_code == 201, r.text
    assert len(feed(client, citizen["headers"])["items"]) == before

    r = client.post(
        f"/api/appeals/{aid}/comments",
        json={"body": "Бригада выедет завтра", "is_internal": False},
        headers=operator.headers,
    )
    assert r.status_code == 201, r.text
    body = feed(client, citizen["headers"])
    assert len(body["items"]) == before + 1
    assert "Бригада" not in str(body)


def test_citizen_comment_notifies_assignee(client, engine, citizen, my_appeal, make_user):
    aid, number = my_appeal
    operator = make_user("operator")
    with engine.begin() as c:
        c.execute(text("UPDATE appeals SET assignee_id = :u WHERE id = :i"), {"u": operator.id, "i": aid})
    r = client.post(f"/api/my/appeals/{number}/comments", json={"body": "Добавляю детали"}, headers=citizen["headers"])
    assert r.status_code == 201, r.text
    items = feed(client, operator.headers)["items"]
    assert any(n["kind"] == "citizen_comment" and number in n["message"] for n in items)


def test_feed_is_private(client, citizen, my_appeal, make_user):
    aid, number = my_appeal
    operator = make_user("operator")
    client.post(f"/api/appeals/{aid}/status", json={"to_status": "accepted"}, headers=operator.headers)
    assert all(number not in n["message"] or n["kind"] != "appeal_update" for n in feed(client, operator.headers)["items"])
