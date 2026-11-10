"""Личный кабинет гражданина и привязка обращений. Нужна тестовая база."""
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
def citizens(client, engine):
    """Фабрика граждан; пользователи и их обращения удаляются после теста."""
    made = []

    def make():
        email = f"pytest_{uuid.uuid4().hex[:10]}@example.com"
        r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
        assert r.status_code == 201
        user = r.json()["user"]
        made.append(user["id"])
        return {"id": user["id"], "email": email, "headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}

    yield make
    with engine.begin() as c:
        for uid in made:
            c.execute(text("DELETE FROM appeals WHERE citizen_id = :u"), {"u": uid})
            c.execute(text("DELETE FROM audit_log WHERE user_id = :u"), {"u": uid})
            c.execute(text("DELETE FROM appeal_comments WHERE author_id = :u"), {"u": uid})
            c.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})


@pytest.fixture
def appeal(engine, make_user, citizens):
    """Фабрика обращений гражданина (зависит от make_user и citizens: порядок очистки)."""
    ids = []

    def make(citizen_id, status="new", response_text=None):
        with engine.begin() as c:
            row = c.execute(
                text(
                    "INSERT INTO appeals (text, created_at, status, citizen_id, response_text) "
                    "VALUES (:t, now(), :s, :c, :r) RETURNING id, public_number"
                ),
                {"t": BODY, "s": status, "c": citizen_id, "r": response_text},
            ).one()
        ids.append(row.id)
        return row.id, row.public_number

    yield make
    with engine.begin() as c:
        for i in ids:
            c.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": i})


def submit(client, headers=None):
    return client.post("/api/public/appeals", data={"text": BODY}, headers=headers or {})


def db_row(engine, number):
    with engine.connect() as c:
        return c.execute(
            text("SELECT id, citizen_id, contact_email FROM appeals WHERE public_number = :n"), {"n": number}
        ).one()


# ------------------------------- привязка при подаче -------------------------------

def test_logged_in_citizen_submission_is_linked(client, engine, citizens):
    cit = citizens()
    r = submit(client, cit["headers"])
    assert r.status_code == 201
    row = db_row(engine, r.json()["public_number"])
    assert row.citizen_id == cit["id"] and row.contact_email == cit["email"]


def test_anonymous_submission_has_no_owner(client, engine, citizens):
    citizens()
    r = submit(client)
    row = db_row(engine, r.json()["public_number"])
    assert row.citizen_id is None
    with engine.begin() as c:
        c.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": row.id})


def test_staff_token_does_not_link(client, engine, make_user):
    staff = make_user("operator")
    r = submit(client, staff.headers)
    assert r.status_code == 201
    row = db_row(engine, r.json()["public_number"])
    assert row.citizen_id is None
    with engine.begin() as c:
        c.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": row.id})


def test_garbage_token_is_treated_as_anonymous(client, engine):
    r = submit(client, {"Authorization": "Bearer not-a-token"})
    assert r.status_code == 201
    row = db_row(engine, r.json()["public_number"])
    assert row.citizen_id is None
    with engine.begin() as c:
        c.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": row.id})


# ------------------------------------ мои обращения ----------------------------------

def test_list_contains_only_own(client, citizens, appeal, make_user):
    a, b = citizens(), citizens()
    _, num_a = appeal(a["id"])
    _, num_b = appeal(b["id"])
    got = client.get("/api/my/appeals", headers=a["headers"]).json()
    numbers = [x["public_number"] for x in got]
    assert num_a in numbers and num_b not in numbers
    assert got[0]["status_label"] == "Зарегистрировано"


def test_foreign_and_malformed_numbers_are_404(client, citizens, appeal):
    a, b = citizens(), citizens()
    _, num_b = appeal(b["id"])
    assert client.get(f"/api/my/appeals/{num_b}", headers=a["headers"]).status_code == 404
    assert client.get("/api/my/appeals/abc", headers=a["headers"]).status_code == 404
    assert client.post(f"/api/my/appeals/{num_b}/comments", json={"body": "x"}, headers=a["headers"]).status_code == 404


def test_detail_hides_internal_notes_and_staff_identity(client, engine, citizens, appeal, make_user):
    cit = citizens()
    staff = make_user("operator")
    appeal_id, number = appeal(cit["id"])
    with engine.begin() as c:
        for body, internal in (("Секретная заметка", True), ("Ответ сотрудника гражданину", False)):
            c.execute(
                text("INSERT INTO appeal_comments (appeal_id, author_id, body, is_internal) VALUES (:i, :u, :b, :n)"),
                {"i": appeal_id, "u": staff.id, "b": body, "n": internal},
            )
    r = client.get(f"/api/my/appeals/{number}", headers=cit["headers"])
    assert r.status_code == 200
    bodies = [m["body"] for m in r.json()["messages"]]
    assert bodies == ["Ответ сотрудника гражданину"]
    assert r.json()["messages"][0]["mine"] is False
    assert "Секретная" not in r.text and staff.email not in r.text


def test_response_text_only_after_closing(client, citizens, appeal):
    cit = citizens()
    _, open_number = appeal(cit["id"], status="accepted", response_text="черновик ответа")
    _, done_number = appeal(cit["id"], status="resolved", response_text="Фонарь заменили")
    assert client.get(f"/api/my/appeals/{open_number}", headers=cit["headers"]).json()["response_text"] is None
    done = client.get(f"/api/my/appeals/{done_number}", headers=cit["headers"]).json()
    assert done["response_text"] == "Фонарь заменили" and done["can_comment"] is False


def test_reject_reason_is_shown(client, engine, citizens, appeal):
    cit = citizens()
    appeal_id, number = appeal(cit["id"], status="rejected")
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO appeal_status_history (appeal_id, from_status, to_status, comment) "
                 "VALUES (:i, 'new', 'rejected', 'Не относится к компетенции города')"),
            {"i": appeal_id},
        )
    got = client.get(f"/api/my/appeals/{number}", headers=cit["headers"]).json()
    assert got["reject_reason"] == "Не относится к компетенции города"


# ------------------------------------- дополнения ------------------------------------

def test_citizen_comment_is_visible_to_staff(client, citizens, appeal, make_user):
    cit = citizens()
    staff = make_user("operator")
    appeal_id, number = appeal(cit["id"])
    r = client.post(f"/api/my/appeals/{number}/comments", json={"body": "  Уточняю: подъезд 3  "}, headers=cit["headers"])
    assert r.status_code == 201
    assert r.json()["messages"][-1] == {**r.json()["messages"][-1], "body": "Уточняю: подъезд 3", "mine": True}
    card = client.get(f"/api/appeals/{appeal_id}", headers=staff.headers).json()
    mine = [c for c in card["comments"] if "подъезд 3" in c["body"]]
    assert len(mine) == 1 and mine[0]["is_internal"] is False


def test_cannot_comment_on_closed_appeal(client, citizens, appeal):
    cit = citizens()
    _, number = appeal(cit["id"], status="resolved")
    r = client.post(f"/api/my/appeals/{number}/comments", json={"body": "ещё вопрос"}, headers=cit["headers"])
    assert r.status_code == 409


@pytest.mark.parametrize("body", ["", "   "])
def test_empty_comment_rejected(client, citizens, appeal, body):
    cit = citizens()
    _, number = appeal(cit["id"])
    assert client.post(f"/api/my/appeals/{number}/comments", json={"body": body}, headers=cit["headers"]).status_code == 422


def test_comments_are_rate_limited(client, citizens, appeal):
    cit = citizens()
    _, number = appeal(cit["id"])
    for _ in range(20):
        assert client.post(f"/api/my/appeals/{number}/comments", json={"body": "ещё"}, headers=cit["headers"]).status_code == 201
    assert client.post(f"/api/my/appeals/{number}/comments", json={"body": "ещё"}, headers=cit["headers"]).status_code == 429


# ----------------------------------- доступ по ролям ---------------------------------

@pytest.mark.parametrize("role", ["operator", "analyst", "manager", "admin", "executor"])
def test_staff_cannot_use_citizen_area(client, make_user, role):
    user = make_user(role)
    assert client.get("/api/my/appeals", headers=user.headers).status_code == 403


def test_citizen_area_requires_login(client):
    assert client.get("/api/my/appeals").status_code == 401
