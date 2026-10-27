import functools
import os
import uuid
from types import SimpleNamespace

import pytest

# Интеграционные тесты идут в базу из APPEALS_TEST_DATABASE_URL (если задана).
# Переменная выставляется ДО импорта приложения, чтобы engine смотрел в нужную базу.
_test_url = os.environ.get("APPEALS_TEST_DATABASE_URL")
if _test_url:
    os.environ["APPEALS_DATABASE_URL"] = _test_url

TEST_EMAIL_LIKE = "pytest-%@example.test"
DEFAULT_PASSWORD = "Test-Passw0rd"


@functools.cache
def _hash_of(password: str) -> str:
    from app.services.security import hash_password
    return hash_password(password)  # хеширование медленное (так задумано): считаем один раз на пароль


@pytest.fixture
def make_user():
    """Фабрика тестовых пользователей: make_user(role) -> объект с id, email, password, headers.
    После теста удаляются только пользователи pytest-*@example.test и связанные с ними записи."""
    from sqlalchemy import text

    from app.db import engine
    from app.services.security import create_access_token

    def _make(role="admin", password=DEFAULT_PASSWORD, active=True):
        email = f"pytest-{role}-{uuid.uuid4().hex[:8]}@example.test"
        with engine.begin() as c:
            uid = c.execute(
                text("INSERT INTO users (email, password_hash, full_name, role, is_active) "
                     "VALUES (:e, :h, 'Pytest', :r, :a) RETURNING id"),
                {"e": email, "h": _hash_of(password), "r": role, "a": active},
            ).scalar_one()
        token, _ = create_access_token(uid, role)
        return SimpleNamespace(id=uid, email=email, password=password, headers={"Authorization": f"Bearer {token}"})

    yield _make

    with engine.begin() as c:
        c.execute(text(
            "DELETE FROM audit_log WHERE user_id IN (SELECT id FROM users WHERE email LIKE :p) "
            "OR details->>'email' LIKE :p"), {"p": TEST_EMAIL_LIKE})
        c.execute(text("DELETE FROM import_batches WHERE uploaded_by IN (SELECT id FROM users WHERE email LIKE :p)"),
                  {"p": TEST_EMAIL_LIKE})
        c.execute(text("DELETE FROM users WHERE email LIKE :p"), {"p": TEST_EMAIL_LIKE})
