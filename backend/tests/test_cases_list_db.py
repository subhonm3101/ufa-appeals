"""Рабочий список обращений /api/cases и /api/departments. Нужна тестовая база."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

URL = "/api/cases"


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def engine():
    from app.db import engine
    return engine


@pytest.fixture
def tag():
    """Уникальная метка: по ней поиск отделяет обращения теста от любых других в базе."""
    return f"pytest{uuid.uuid4().hex[:10]}"


@pytest.fixture
def appeal(engine, make_user, tag):
    """Фабрика обращений с меткой в тексте. Зависит от make_user: обращения удаляются раньше пользователей."""
    ids = []

    def make(**extra):
        # переданные значения заменяют значения по умолчанию
        params = {"text": f"{tag} тестовое обращение", "created_at": "2026-03-05 10:00+05", **extra}
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


def get(client, user, tag, **params):
    return client.get(URL, params={"q": tag, **params}, headers=user.headers)


def ids(response):
    return [item["id"] for item in response.json()["items"]]


def test_requires_login(client):
    assert client.get(URL).status_code == 401


def test_item_fields(client, appeal, make_user, tag):
    user = make_user("operator")
    appeal_id = appeal()
    r = get(client, user, tag)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["limit"] == 50 and body["offset"] == 0
    item = body["items"][0]
    assert item["id"] == appeal_id
    assert item["public_number"] == f"UFA-2026-{appeal_id:06d}"
    assert item["status"] == "new" and item["is_overdue"] is False
    assert item["excerpt"].startswith(tag)
    assert item["assignee_id"] is None and item["due_at"] is None


def test_filter_by_status_and_counts(client, appeal, make_user, tag):
    user = make_user("operator")
    a_new, a_work, a_work2 = appeal(), appeal(status="in_progress"), appeal(status="in_progress")
    r = get(client, user, tag, status="in_progress")
    assert sorted(ids(r)) == sorted([a_work, a_work2])
    assert r.json()["total"] == 2
    counts = r.json()["status_counts"]  # счётчики не зависят от выбранного статуса
    assert counts["new"] == 1 and counts["in_progress"] == 2 and counts["resolved"] == 0
    assert set(counts) == {"new", "accepted", "in_progress", "waiting", "resolved", "rejected"}
    assert a_new not in ids(r)


def test_unknown_status_and_assignee_rejected(client, make_user, tag):
    user = make_user("operator")
    assert get(client, user, tag, status="open").status_code == 422
    assert get(client, user, tag, assignee="abc").status_code == 422
    assert get(client, user, tag, assignee="99999999999").status_code == 422


def test_assignee_filters(client, appeal, make_user, tag):
    operator, executor = make_user("operator"), make_user("executor")
    mine = appeal(assignee_id=operator.id)  # назначение «на себя» для проверки me
    theirs = appeal(assignee_id=executor.id)
    free = appeal()
    assert ids(get(client, operator, tag, assignee="me")) == [mine]
    assert ids(get(client, operator, tag, assignee="none")) == [free]
    assert ids(get(client, operator, tag, assignee=str(executor.id))) == [theirs]


def test_executor_sees_only_own_whatever_is_requested(client, appeal, make_user, tag):
    executor = make_user("executor")
    own = appeal(assignee_id=executor.id)
    appeal()
    appeal(assignee_id=None)
    for assignee in (None, "none", "me", "1"):
        params = {} if assignee is None else {"assignee": assignee}
        r = get(client, executor, tag, **params)
        assert r.status_code == 200
        assert ids(r) == [own]


def test_overdue_filter(client, appeal, make_user, tag):
    user = make_user("operator")
    late = appeal(status="in_progress", due_at="2020-01-01 00:00+00")
    appeal(status="resolved", due_at="2020-01-01 00:00+00")
    appeal(status="in_progress", due_at="2999-01-01 00:00+00")
    appeal()
    r = get(client, user, tag, overdue="true")
    assert ids(r) == [late]
    assert r.json()["items"][0]["is_overdue"] is True


def test_search_by_public_number(client, appeal, make_user, tag):
    user = make_user("operator")
    appeal_id = appeal()
    appeal()
    r = client.get(URL, params={"q": f"UFA-2026-{appeal_id:06d}"}, headers=user.headers)
    assert ids(r) == [appeal_id]


def test_search_escapes_wildcards(client, appeal, make_user, tag):
    user = make_user("operator")
    appeal()  # текст: «<метка> тестовое обращение»
    assert get(client, user, tag).json()["total"] == 1
    # без экранирования «%» и «_» сработали бы как шаблоны и нашли бы это обращение
    for suffix in ("%", "_", "_тестовое"):
        r = client.get(URL, params={"q": f"{tag}{suffix}"}, headers=user.headers)
        assert r.json()["total"] == 0, suffix


def test_date_filters_use_local_dates(client, appeal, make_user, tag):
    user = make_user("operator")
    early = appeal(created_at="2026-03-05 10:00+05")
    late = appeal(created_at="2026-03-10 10:00+05")
    assert ids(get(client, user, tag, date_from="2026-03-08")) == [late]
    assert ids(get(client, user, tag, date_to="2026-03-05")) == [early]


def test_sorting_and_paging(client, appeal, make_user, tag):
    user = make_user("operator")
    first = appeal(created_at="2026-03-01 10:00+05", due_at="2026-04-10 00:00+05")
    second = appeal(created_at="2026-03-02 10:00+05", due_at="2026-04-01 00:00+05")
    third = appeal(created_at="2026-03-03 10:00+05")  # без срока: в конце при сортировке по сроку
    assert ids(get(client, user, tag)) == [third, second, first]
    assert ids(get(client, user, tag, sort="due")) == [second, first, third]
    page = get(client, user, tag, limit=2, offset=2).json()
    assert page["total"] == 3 and [i["id"] for i in page["items"]] == [first]


def test_departments_list(client, make_user, engine):
    code = f"pytest_{uuid.uuid4().hex[:8]}"
    with engine.begin() as c:
        dep = c.execute(
            text("INSERT INTO departments (code, name) VALUES (:c, :n) RETURNING id"),
            {"c": code, "n": f"Отдел {code}"},
        ).scalar_one()
    try:
        analyst = make_user("analyst")
        r = client.get("/api/departments", headers=analyst.headers)
        assert r.status_code == 200
        assert {"id": dep, "name": f"Отдел {code}"} in r.json()
        assert client.get("/api/departments").status_code == 401
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM departments WHERE id = :i"), {"i": dep})
