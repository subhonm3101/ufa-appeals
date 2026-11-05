"""Схема рабочего процесса обращений (миграция 0007). Нужна тестовая база."""
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)


@pytest.fixture
def engine():
    from app.db import engine
    return engine


@pytest.fixture
def created(engine):
    """Список id обращений, которые тест создал; после теста они удаляются."""
    ids = []
    yield ids
    with engine.begin() as c:
        for appeal_id in ids:
            c.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": appeal_id})


def add_appeal(engine, created, created_at="2026-03-05 10:00+05", **extra):
    columns = ["text", "created_at", *extra]
    values = [":text", ":created_at", *(f":{k}" for k in extra)]
    with engine.begin() as c:
        row = c.execute(
            text(
                f"INSERT INTO appeals ({', '.join(columns)}) "
                f"VALUES ({', '.join(values)}) RETURNING id, public_number"
            ),
            {"text": "Тестовое обращение", "created_at": created_at, **extra},
        ).one()
    created.append(row.id)
    return row


def test_public_number_is_assigned_by_database(engine, created):
    row = add_appeal(engine, created)
    assert row.public_number == f"UFA-2026-{row.id:06d}"


def test_public_number_year_uses_local_time(engine, created):
    # 31 декабря 23:30 UTC в Уфе (UTC+5) уже 1 января следующего года
    row = add_appeal(engine, created, created_at="2026-12-31 23:30+00")
    assert row.public_number.startswith("UFA-2027-")


def test_explicit_public_number_is_kept(engine, created):
    number = f"UFA-TEST-{uuid.uuid4().hex[:8]}"
    row = add_appeal(engine, created, public_number=number)
    assert row.public_number == number


def test_public_numbers_are_unique(engine, created):
    number = f"UFA-TEST-{uuid.uuid4().hex[:8]}"
    add_appeal(engine, created, public_number=number)
    with pytest.raises(IntegrityError):
        add_appeal(engine, created, public_number=number)


def test_new_appeal_defaults(engine, created):
    row = add_appeal(engine, created)
    with engine.connect() as c:
        got = c.execute(
            text("SELECT status, source, assignee_id, due_at FROM appeals WHERE id = :i"),
            {"i": row.id},
        ).one()
    assert (got.status, got.source) == ("new", "import")
    assert got.assignee_id is None and got.due_at is None


@pytest.mark.parametrize("status", ["new", "accepted", "in_progress", "waiting", "resolved", "rejected"])
def test_allowed_statuses(engine, created, status):
    add_appeal(engine, created, status=status)


def test_unknown_status_rejected(engine, created):
    with pytest.raises(IntegrityError):
        add_appeal(engine, created, status="open")


def test_unknown_source_rejected(engine, created):
    with pytest.raises(IntegrityError):
        add_appeal(engine, created, source="telegram")


def test_history_and_comments_are_deleted_with_appeal(engine, created):
    row = add_appeal(engine, created)
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO appeal_status_history (appeal_id, to_status) VALUES (:i, 'new')"),
            {"i": row.id},
        )
        c.execute(
            text("INSERT INTO appeal_comments (appeal_id, body) VALUES (:i, 'проверка')"),
            {"i": row.id},
        )
        c.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": row.id})
        left = c.execute(
            text(
                "SELECT (SELECT count(*) FROM appeal_status_history WHERE appeal_id = :i) "
                "+ (SELECT count(*) FROM appeal_comments WHERE appeal_id = :i)"
            ),
            {"i": row.id},
        ).scalar_one()
    assert left == 0


def test_comment_is_internal_by_default(engine, created):
    row = add_appeal(engine, created)
    with engine.begin() as c:
        internal = c.execute(
            text("INSERT INTO appeal_comments (appeal_id, body) VALUES (:i, 'x') RETURNING is_internal"),
            {"i": row.id},
        ).scalar_one()
    assert internal is True


def _insert_user(engine, role, department_id=None):
    email = f"pytest_{uuid.uuid4().hex[:10]}@example.com"
    with engine.begin() as c:
        return c.execute(
            text(
                "INSERT INTO users (email, password_hash, role, department_id) "
                "VALUES (:e, 'x', :r, :d) RETURNING id"
            ),
            {"e": email, "r": role, "d": department_id},
        ).scalar_one()


def _delete_user(engine, user_id):
    with engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id = :i"), {"i": user_id})


def test_executor_role_is_allowed_and_citizen_is_not_yet(engine):
    user_id = _insert_user(engine, "executor")
    _delete_user(engine, user_id)
    with pytest.raises(IntegrityError):
        _insert_user(engine, "citizen")


def test_user_can_belong_to_department(engine):
    code = f"pytest_{uuid.uuid4().hex[:8]}"
    with engine.begin() as c:
        dept = c.execute(
            text("INSERT INTO departments (code, name) VALUES (:c, :n) RETURNING id"),
            {"c": code, "n": f"Отдел {code}"},
        ).scalar_one()
    user_id = _insert_user(engine, "executor", dept)
    try:
        with engine.connect() as c:
            got = c.execute(text("SELECT department_id FROM users WHERE id = :i"), {"i": user_id}).scalar_one()
        assert got == dept
    finally:
        _delete_user(engine, user_id)
        with engine.begin() as c:
            c.execute(text("DELETE FROM departments WHERE id = :i"), {"i": dept})
