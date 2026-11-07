"""Уведомления внутри системы. Нужна тестовая база."""
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

URL = "/api/notifications"


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def engine():
    from app.db import engine
    return engine


@pytest.fixture
def appeal(engine, make_user):
    """Фабрика обращений. Зависит от make_user: обращения удаляются раньше пользователей."""
    ids = []

    def make(**extra):
        params = {"text": "Тестовое обращение", "created_at": "2026-03-05 10:00+05", **extra}
        columns = ", ".join(params)
        values = ", ".join(f":{k}" for k in params)
        with engine.begin() as c:
            appeal_id = c.execute(
                text(f"INSERT INTO appeals ({columns}) VALUES ({values}) RETURNING id"), params
            ).scalar_one()
        ids.append(appeal_id)
        return appeal_id

    yield make
    with engine.begin() as c:
        for appeal_id in ids:
            c.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": appeal_id})


def inbox(client, user, **params):
    r = client.get(URL, params={"limit": 100, **params}, headers=user.headers)
    assert r.status_code == 200, r.text
    return r.json()


def kinds_for(body, appeal_id):
    return [n["kind"] for n in body["items"] if n["appeal_id"] == appeal_id]


def days_from_now(days):
    return datetime.now(timezone.utc) + timedelta(days=days)


def test_requires_login(client):
    assert client.get(URL).status_code == 401
    assert client.get(f"{URL}/unread-count").status_code == 401
    assert client.post(f"{URL}/read-all").status_code == 401


def test_assignment_notifies_executor_only(client, appeal, make_user):
    operator, executor = make_user("operator"), make_user("executor")
    appeal_id = appeal()
    r = client.post(f"/api/appeals/{appeal_id}/assign", json={"assignee_id": executor.id}, headers=operator.headers)
    assert r.status_code == 200
    body = inbox(client, executor)
    assert body["unread"] == 1 and body["total"] == 1
    note = body["items"][0]
    assert note["kind"] == "assigned" and note["appeal_id"] == appeal_id and note["read_at"] is None
    assert f"UFA-2026-{appeal_id:06d}" in note["message"]
    assert inbox(client, operator)["total"] == 0


def test_status_change_notifies_assignee_but_not_the_actor(client, appeal, make_user):
    manager, executor = make_user("manager"), make_user("executor")
    appeal_id = appeal(status="accepted", assignee_id=executor.id)
    own = client.post(f"/api/appeals/{appeal_id}/status", json={"to_status": "in_progress"}, headers=executor.headers)
    assert own.status_code == 200
    assert inbox(client, executor)["total"] == 0  # своё действие не уведомляет
    other = client.post(
        f"/api/appeals/{appeal_id}/status",
        json={"to_status": "rejected", "comment": "Дубликат"},
        headers=manager.headers,
    )
    assert other.status_code == 200
    body = inbox(client, executor)
    assert kinds_for(body, appeal_id) == ["status_changed"]
    assert "В работе → Отклонено" in body["items"][0]["message"]


def test_due_soon_reminder_is_sent_once(client, appeal, make_user):
    executor = make_user("executor")
    appeal_id = appeal(status="in_progress", assignee_id=executor.id, due_at=days_from_now(1))
    for _ in range(3):  # повторные обращения за уведомлениями не создают дублей
        body = inbox(client, executor)
    assert kinds_for(body, appeal_id) == ["due_soon"]


def test_no_reminder_for_far_or_closed_appeals(client, appeal, make_user):
    executor = make_user("executor")
    far = appeal(status="in_progress", assignee_id=executor.id, due_at=days_from_now(20))
    closed = appeal(status="resolved", assignee_id=executor.id, due_at=days_from_now(-5))
    no_due = appeal(status="in_progress", assignee_id=executor.id)
    body = inbox(client, executor)
    assert all(kinds_for(body, a) == [] for a in (far, closed, no_due))


def test_overdue_reminder_for_assignee(client, appeal, make_user):
    executor = make_user("executor")
    appeal_id = appeal(status="in_progress", assignee_id=executor.id, due_at=days_from_now(-2))
    for _ in range(2):
        body = inbox(client, executor)
    assert kinds_for(body, appeal_id) == ["overdue"]
    assert "Просрочено" in body["items"][0]["message"]


def test_managers_get_overdue_for_all_appeals(client, appeal, make_user):
    manager, operator = make_user("manager"), make_user("operator")
    appeal_id = appeal(status="in_progress", due_at=days_from_now(-3))  # исполнителя нет
    assert kinds_for(inbox(client, manager), appeal_id) == ["overdue"]
    assert kinds_for(inbox(client, operator), appeal_id) == []


def test_mark_read_and_unread_count(client, appeal, make_user):
    operator, executor = make_user("operator"), make_user("executor")
    first, second = appeal(), appeal()
    for appeal_id in (first, second):
        client.post(f"/api/appeals/{appeal_id}/assign", json={"assignee_id": executor.id}, headers=operator.headers)
    body = inbox(client, executor)
    assert body["unread"] == 2
    assert client.get(f"{URL}/unread-count", headers=executor.headers).json() == {"unread": 2}

    target = body["items"][0]["id"]
    assert client.post(f"{URL}/{target}/read", headers=executor.headers).status_code == 200
    assert client.get(f"{URL}/unread-count", headers=executor.headers).json() == {"unread": 1}
    unread_only = inbox(client, executor, unread_only="true")
    assert unread_only["total"] == 1 and unread_only["items"][0]["id"] != target

    done = client.post(f"{URL}/read-all", headers=executor.headers)
    assert done.status_code == 200 and done.json() == {"marked": 1}
    assert client.get(f"{URL}/unread-count", headers=executor.headers).json() == {"unread": 0}


def test_cannot_touch_foreign_notification(client, appeal, make_user):
    operator, executor, other = make_user("operator"), make_user("executor"), make_user("executor")
    appeal_id = appeal()
    client.post(f"/api/appeals/{appeal_id}/assign", json={"assignee_id": executor.id}, headers=operator.headers)
    note_id = inbox(client, executor)["items"][0]["id"]
    assert client.post(f"{URL}/{note_id}/read", headers=other.headers).status_code == 404
    assert inbox(client, executor)["unread"] == 1
    assert client.post(f"{URL}/2147483000/read", headers=other.headers).status_code == 404
