"""API работы с обращением: карточка, статусы, назначение, комментарии. Нужна тестовая база."""
import os
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

STRONG_PASSWORD = "Xk9#mQ2$vLp7wZ"


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def engine():
    from app.db import engine
    return engine


def _department(engine):
    code = f"pytest_{uuid.uuid4().hex[:8]}"
    with engine.begin() as c:
        dep_id = c.execute(
            text("INSERT INTO departments (code, name) VALUES (:c, :n) RETURNING id"),
            {"c": code, "n": f"Отдел {code}"},
        ).scalar_one()
    return dep_id


@pytest.fixture
def department(engine):
    dep_id = _department(engine)
    yield dep_id
    with engine.begin() as c:
        # пользователей и обращения отвязываем сами: порядок очистки фикстур не гарантирован
        c.execute(text("UPDATE users SET department_id = NULL WHERE department_id = :i"), {"i": dep_id})
        c.execute(text("UPDATE appeals SET department_id = NULL WHERE department_id = :i"), {"i": dep_id})
        c.execute(text("DELETE FROM departments WHERE id = :i"), {"i": dep_id})


@pytest.fixture
def other_department(engine):
    dep_id = _department(engine)
    yield dep_id
    with engine.begin() as c:
        # пользователей и обращения отвязываем сами: порядок очистки фикстур не гарантирован
        c.execute(text("UPDATE users SET department_id = NULL WHERE department_id = :i"), {"i": dep_id})
        c.execute(text("UPDATE appeals SET department_id = NULL WHERE department_id = :i"), {"i": dep_id})
        c.execute(text("DELETE FROM departments WHERE id = :i"), {"i": dep_id})


@pytest.fixture
def appeal(engine, make_user):
    """Фабрика обращений. Зависит от make_user, чтобы обращения удалялись раньше пользователей."""
    ids = []

    def make(**extra):
        columns = ["text", "created_at", *extra]
        values = [":text", ":created_at", *(f":{k}" for k in extra)]
        params = {"text": "Тестовое обращение", "created_at": "2026-03-05 10:00+05", **extra}
        with engine.begin() as c:
            appeal_id = c.execute(
                text(f"INSERT INTO appeals ({', '.join(columns)}) VALUES ({', '.join(values)}) RETURNING id"),
                params,
            ).scalar_one()
        ids.append(appeal_id)
        return appeal_id

    yield make
    with engine.begin() as c:
        for appeal_id in ids:
            c.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": appeal_id})


def set_department(engine, user, department_id):
    with engine.begin() as c:
        c.execute(text("UPDATE users SET department_id = :d WHERE id = :i"), {"d": department_id, "i": user.id})


def post_status(client, user, appeal_id, to_status, **extra):
    return client.post(
        f"/api/appeals/{appeal_id}/status", json={"to_status": to_status, **extra}, headers=user.headers
    )


# ----------------------------------- карточка -----------------------------------

def test_card_requires_login(client, appeal, make_user):
    assert client.get(f"/api/appeals/{appeal()}").status_code == 401


def test_card_not_found(client, make_user):
    user = make_user("operator")
    assert client.get("/api/appeals/2147483000", headers=user.headers).status_code == 404


def test_card_contents(client, appeal, make_user):
    user = make_user("operator")
    appeal_id = appeal()
    r = client.get(f"/api/appeals/{appeal_id}", headers=user.headers)
    assert r.status_code == 200
    card = r.json()
    assert card["public_number"] == f"UFA-2026-{appeal_id:06d}"
    assert card["status"] == "new" and card["source"] == "import"
    assert card["allowed_transitions"] == ["accepted", "rejected"]
    assert card["history"] == [] and card["comments"] == []
    assert card["is_overdue"] is False


def test_analyst_can_view_but_not_change(client, appeal, make_user):
    analyst = make_user("analyst")
    appeal_id = appeal()
    card = client.get(f"/api/appeals/{appeal_id}", headers=analyst.headers)
    assert card.status_code == 200 and card.json()["allowed_transitions"] == []
    assert post_status(client, analyst, appeal_id, "accepted").status_code == 403
    r = client.post(f"/api/appeals/{appeal_id}/comments", json={"body": "x"}, headers=analyst.headers)
    assert r.status_code == 403


def test_overdue_flag(client, appeal, make_user):
    user = make_user("operator")
    late = appeal(status="in_progress", due_at="2020-01-01 00:00+00")
    done = appeal(status="resolved", due_at="2020-01-01 00:00+00")
    assert client.get(f"/api/appeals/{late}", headers=user.headers).json()["is_overdue"] is True
    assert client.get(f"/api/appeals/{done}", headers=user.headers).json()["is_overdue"] is False


# ----------------------------------- статусы -----------------------------------

def test_accept_sets_due_date_and_history(client, appeal, make_user):
    user = make_user("operator")
    appeal_id = appeal()
    r = post_status(client, user, appeal_id, "accepted", comment="Проверено")
    assert r.status_code == 200
    card = r.json()
    assert card["status"] == "accepted"
    created = datetime.fromisoformat(card["created_at"])
    assert datetime.fromisoformat(card["due_at"]) - created == timedelta(days=30)
    assert [(h["from_status"], h["to_status"], h["comment"]) for h in card["history"]] == [
        ("new", "accepted", "Проверено")
    ]
    assert card["history"][0]["changed_by"] == user.email


def test_invalid_transition_and_same_status(client, appeal, make_user):
    user = make_user("operator")
    appeal_id = appeal()
    assert post_status(client, user, appeal_id, "resolved", response_text="ok").status_code == 409
    assert post_status(client, user, appeal_id, "new").status_code == 409
    assert post_status(client, user, appeal_id, "nonsense").status_code == 422


def test_rejection_needs_reason(client, appeal, make_user):
    user = make_user("operator")
    appeal_id = appeal()
    assert post_status(client, user, appeal_id, "rejected").status_code == 422
    r = post_status(client, user, appeal_id, "rejected", comment="Не относится к компетенции города")
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_resolution_needs_response_and_sets_resolved_at(client, appeal, make_user):
    user = make_user("operator")
    appeal_id = appeal(status="in_progress")
    assert post_status(client, user, appeal_id, "resolved").status_code == 422
    r = post_status(client, user, appeal_id, "resolved", response_text="Фонарь заменён")
    card = r.json()
    assert r.status_code == 200 and card["resolved_at"] is not None
    assert card["response_text"] == "Фонарь заменён"
    assert card["allowed_transitions"] == []


def test_reopen_only_by_manager(client, appeal, make_user):
    operator, manager = make_user("operator"), make_user("manager")
    appeal_id = appeal(status="resolved", resolved_at="2026-03-06 10:00+05")
    assert post_status(client, operator, appeal_id, "in_progress").status_code == 403
    r = post_status(client, manager, appeal_id, "in_progress")
    assert r.status_code == 200 and r.json()["resolved_at"] is None


def test_status_change_is_audited(client, appeal, make_user, engine):
    user = make_user("operator")
    appeal_id = appeal()
    assert post_status(client, user, appeal_id, "accepted").status_code == 200
    with engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM audit_log WHERE user_id = :u AND action = 'appeal_status_changed'"),
            {"u": user.id},
        ).scalar_one()
    assert n == 1


def test_unknown_appeal_status_change(client, make_user):
    user = make_user("operator")
    assert post_status(client, user, 2147483000, "accepted").status_code == 404


# ----------------------------------- исполнитель -----------------------------------

def test_executor_sees_and_changes_only_own_appeals(client, appeal, make_user):
    executor = make_user("executor")
    own = appeal(status="accepted", assignee_id=executor.id)
    foreign = appeal(status="accepted")
    assert client.get(f"/api/appeals/{foreign}", headers=executor.headers).status_code == 403
    assert post_status(client, executor, foreign, "in_progress").status_code == 403
    assert client.get(f"/api/appeals/{own}", headers=executor.headers).status_code == 200
    r = post_status(client, executor, own, "in_progress")
    assert r.status_code == 200 and r.json()["status"] == "in_progress"


def test_executor_cannot_reject_and_can_comment_own(client, appeal, make_user):
    executor = make_user("executor")
    own = appeal(status="in_progress", assignee_id=executor.id)
    foreign = appeal(status="in_progress")
    assert post_status(client, executor, own, "rejected", comment="нет").status_code == 403
    ok = client.post(f"/api/appeals/{own}/comments", json={"body": "Выехали на место"}, headers=executor.headers)
    assert ok.status_code == 201
    bad = client.post(f"/api/appeals/{foreign}/comments", json={"body": "x"}, headers=executor.headers)
    assert bad.status_code == 403


# ----------------------------------- назначение -----------------------------------

def test_assign_executor_sets_department_and_writes_comment(client, appeal, make_user, department, engine):
    operator, executor = make_user("operator"), make_user("executor")
    set_department(engine, executor, department)
    appeal_id = appeal()
    r = client.post(f"/api/appeals/{appeal_id}/assign", json={"assignee_id": executor.id}, headers=operator.headers)
    assert r.status_code == 200
    card = r.json()
    assert card["assignee_id"] == executor.id and card["department_id"] == department
    assert any(c["body"].startswith("Назначено") and c["is_internal"] for c in card["comments"])


def test_assign_rejects_non_executor_and_empty_request(client, appeal, make_user):
    operator, analyst = make_user("operator"), make_user("analyst")
    appeal_id = appeal()
    url = f"/api/appeals/{appeal_id}/assign"
    assert client.post(url, json={"assignee_id": analyst.id}, headers=operator.headers).status_code == 422
    assert client.post(url, json={}, headers=operator.headers).status_code == 422
    assert client.post(url, json={"department_id": 2147483000}, headers=operator.headers).status_code == 422


def test_assign_department_mismatch(client, appeal, make_user, department, other_department, engine):
    operator, executor = make_user("operator"), make_user("executor")
    set_department(engine, executor, department)
    appeal_id = appeal()
    r = client.post(
        f"/api/appeals/{appeal_id}/assign",
        json={"department_id": other_department, "assignee_id": executor.id},
        headers=operator.headers,
    )
    assert r.status_code == 422


def test_unassign_and_no_change(client, appeal, make_user):
    operator, executor = make_user("operator"), make_user("executor")
    appeal_id = appeal(assignee_id=executor.id)
    url = f"/api/appeals/{appeal_id}/assign"
    assert client.post(url, json={"assignee_id": executor.id}, headers=operator.headers).status_code == 409
    r = client.post(url, json={"assignee_id": None}, headers=operator.headers)
    assert r.status_code == 200 and r.json()["assignee_id"] is None


def test_closed_appeal_cannot_be_assigned(client, appeal, make_user):
    operator, executor = make_user("operator"), make_user("executor")
    appeal_id = appeal(status="resolved")
    r = client.post(f"/api/appeals/{appeal_id}/assign", json={"assignee_id": executor.id}, headers=operator.headers)
    assert r.status_code == 409


def test_executor_cannot_assign(client, appeal, make_user):
    executor = make_user("executor")
    appeal_id = appeal(assignee_id=executor.id)
    r = client.post(f"/api/appeals/{appeal_id}/assign", json={"assignee_id": None}, headers=executor.headers)
    assert r.status_code == 403


# ----------------------------------- комментарии и исполнители -----------------------------------

def test_comment_appears_in_card(client, appeal, make_user):
    user = make_user("operator")
    appeal_id = appeal()
    r = client.post(
        f"/api/appeals/{appeal_id}/comments",
        json={"body": "  Позвонили заявителю  ", "is_internal": False},
        headers=user.headers,
    )
    assert r.status_code == 201 and r.json()["body"] == "Позвонили заявителю"
    comments = client.get(f"/api/appeals/{appeal_id}", headers=user.headers).json()["comments"]
    assert [(c["body"], c["is_internal"], c["author"]) for c in comments] == [
        ("Позвонили заявителю", False, user.email)
    ]


def test_empty_comment_rejected(client, appeal, make_user):
    user = make_user("operator")
    appeal_id = appeal()
    for body in ("", "   "):
        r = client.post(f"/api/appeals/{appeal_id}/comments", json={"body": body}, headers=user.headers)
        assert r.status_code == 422


def test_executors_list(client, make_user, department, other_department, engine):
    operator, analyst = make_user("operator"), make_user("analyst")
    ours, theirs = make_user("executor"), make_user("executor")
    set_department(engine, ours, department)
    set_department(engine, theirs, other_department)
    r = client.get("/api/executors", params={"department_id": department}, headers=operator.headers)
    assert r.status_code == 200
    assert [e["id"] for e in r.json()] == [ours.id]
    assert client.get("/api/executors", headers=analyst.headers).status_code == 403


# ----------------------------------- пользователи с подразделением -----------------------------------

def test_admin_creates_executor_with_department(client, make_user, department, engine):
    admin = make_user("admin")
    email = f"pytest_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/api/users",
        json={"email": email, "password": STRONG_PASSWORD, "role": "executor", "department_id": department},
        headers=admin.headers,
    )
    try:
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "executor" and r.json()["department_id"] == department
        user_id = r.json()["id"]
        cleared = client.patch(f"/api/users/{user_id}", json={"department_id": None}, headers=admin.headers)
        assert cleared.status_code == 200 and cleared.json()["department_id"] is None
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM users WHERE lower(email) = :e"), {"e": email})


def test_unknown_department_rejected_for_user(client, make_user):
    admin = make_user("admin")
    r = client.post(
        "/api/users",
        json={"email": f"pytest_{uuid.uuid4().hex[:8]}@example.com", "password": STRONG_PASSWORD,
              "role": "executor", "department_id": 2147483000},
        headers=admin.headers,
    )
    assert r.status_code == 422
