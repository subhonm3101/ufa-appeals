"""Вход, роли, управление пользователями и журнал: на настоящей базе (при APPEALS_TEST_DATABASE_URL).
Создаются и удаляются только пользователи pytest-*@example.test и их записи."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="не задана APPEALS_TEST_DATABASE_URL",
)

from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
PW = "Test-Passw0rd"


@pytest.fixture(autouse=True)
def cleanup_data(make_user):
    yield
    with engine.begin() as c:
        c.execute(text("DELETE FROM appeals WHERE external_id LIKE 'PYTEST-%'"))
        c.execute(text("DELETE FROM import_batches WHERE filename LIKE 'pytest_%'"))


def login(email, password=PW):
    return client.post("/api/auth/login", data={"username": email, "password": password})


def audit(action, email=None, user_id=None):
    q, p = "SELECT details, user_id, ip FROM audit_log WHERE action = :a", {"a": action}
    if email:
        q += " AND details->>'email' = :e"; p["e"] = email
    if user_id:
        q += " AND user_id = :u"; p["u"] = user_id
    with engine.begin() as c:
        return c.execute(text(q), p).all()


def test_login_success_me_and_audit(make_user):
    u = make_user("analyst")
    r = login(u.email.upper())  # регистр email не важен
    assert r.status_code == 200
    j = r.json()
    assert j["token_type"] == "bearer" and j["user"]["role"] == "analyst" and j["user"]["last_login_at"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {j['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == u.email and me.json()["role"] == "analyst"
    assert len(audit("login", email=u.email)) == 1 and audit("login", email=u.email)[0].ip


def test_wrong_password_and_unknown_email_look_the_same(make_user):
    u = make_user("operator")
    a = login(u.email, "Wrong-Passw0rd")
    ghost = f"pytest-ghost-{uuid.uuid4().hex[:6]}@example.test"
    b = login(ghost)
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    assert len(audit("login_failed", email=u.email)) == 1 and len(audit("login_failed", email=ghost)) == 1


def test_lockout_after_repeated_failures(make_user):
    u = make_user("operator")
    for _ in range(settings.max_failed_logins):
        assert login(u.email, "Wrong-Passw0rd").status_code == 401
    assert login(u.email).status_code == 429          # даже верный пароль не пускает
    assert login(u.email, "Wrong-Passw0rd").status_code == 429
    other = make_user("operator")
    assert login(other.email).status_code == 200      # чужая учётная запись не страдает


def test_successful_login_resets_failure_counter(make_user):
    u = make_user("operator")
    for _ in range(settings.max_failed_logins - 1):
        login(u.email, "Wrong-Passw0rd")
    assert login(u.email).status_code == 200
    for _ in range(settings.max_failed_logins - 1):
        assert login(u.email, "Wrong-Passw0rd").status_code == 401
    assert login(u.email).status_code == 200


def test_inactive_user_loses_access_immediately(make_user):
    u = make_user("analyst")
    assert client.get("/api/auth/me", headers=u.headers).status_code == 200
    with engine.begin() as c:
        c.execute(text("UPDATE users SET is_active = FALSE WHERE id = :i"), {"i": u.id})
    assert client.get("/api/auth/me", headers=u.headers).status_code == 401  # токен ещё не истёк, но доступа нет
    assert login(u.email).status_code == 403
    assert len(audit("login_blocked", email=u.email)) == 1


def test_role_change_applies_immediately(make_user):
    u = make_user("analyst")
    assert client.get("/api/analytics/summary", params={"date_from": "2011-01-01", "date_to": "2011-01-02"}, headers=u.headers).status_code == 200
    with engine.begin() as c:
        c.execute(text("UPDATE users SET role = 'operator' WHERE id = :i"), {"i": u.id})
    assert client.get("/api/analytics/summary", headers=u.headers).status_code == 403  # токен прежний, роль новая


def test_roles_against_real_endpoints(make_user):
    op, an, mg = make_user("operator"), make_user("analyst"), make_user("manager")
    csv = "external_id,text,created_at\nPYTEST-AUTH-1,Тест прав,2010-03-01 10:00\n"
    up = lambda h, **kw: client.post("/api/import", headers=h, files={"file": ("pytest_auth.csv", csv.encode(), "text/csv")}, **kw)
    assert up(an.headers).status_code == 403 and up(mg.headers).status_code == 403
    assert up(op.headers, params={"dry_run": "true"}).status_code == 200
    assert client.get("/api/analytics/summary", params={"date_from": "2011-01-01", "date_to": "2011-01-02"}, headers=mg.headers).status_code == 200
    assert client.get("/api/analytics/summary", headers=op.headers).status_code == 403
    for u in (op, an, mg):
        assert client.get("/api/appeals", params={"limit": 1}, headers=u.headers).status_code == 200
        assert client.get("/api/users", headers=u.headers).status_code == 403


def test_import_records_uploader_in_batch_and_audit(make_user):
    op = make_user("operator")
    csv = "external_id,text,created_at\nPYTEST-AUTH-2,Кто загрузил,2010-03-01 10:00\n"
    r = client.post("/api/import", headers=op.headers, files={"file": ("pytest_auth.csv", csv.encode(), "text/csv")})
    batch = r.json()["batch_id"]
    assert r.status_code == 200 and batch
    with engine.begin() as c:
        assert c.execute(text("SELECT uploaded_by FROM import_batches WHERE id = :b"), {"b": batch}).scalar_one() == op.id
    rows = audit("import", user_id=op.id)
    assert len(rows) == 1 and rows[0].details["inserted"] == 1 and rows[0].details["filename"] == "pytest_auth.csv"


def test_admin_user_management_and_audit(make_user):
    admin = make_user("admin")
    new_email = f"pytest-new-{uuid.uuid4().hex[:6]}@example.test"
    body = {"email": new_email.upper(), "password": "Newpass123", "full_name": "Новый", "role": "operator"}
    r = client.post("/api/users", json=body, headers=admin.headers)
    assert r.status_code == 201 and r.json()["email"] == new_email and r.json()["role"] == "operator"
    uid = r.json()["id"]
    assert "password" not in r.text and "hash" not in r.text
    assert client.post("/api/users", json={**body, "email": new_email}, headers=admin.headers).status_code == 409
    assert client.post("/api/users", json={**body, "email": "x@y"}, headers=admin.headers).status_code == 422
    assert client.post("/api/users", json={**body, "email": "pytest-w@example.test", "password": "weak"}, headers=admin.headers).status_code == 422
    assert client.post("/api/users", json={**body, "email": "pytest-r@example.test", "role": "king"}, headers=admin.headers).status_code == 422
    assert login(new_email, "Newpass123").status_code == 200

    r = client.patch(f"/api/users/{uid}", json={"role": "analyst", "full_name": "Переименован"}, headers=admin.headers)
    assert r.status_code == 200 and r.json()["role"] == "analyst"
    assert client.patch(f"/api/users/{uid}", json={"password": "Resetpass456"}, headers=admin.headers).status_code == 200
    assert login(new_email, "Newpass123").status_code == 401 and login(new_email, "Resetpass456").status_code == 200
    assert client.patch(f"/api/users/{uid}", json={}, headers=admin.headers).status_code == 422
    assert client.patch("/api/users/999999999", json={"role": "manager"}, headers=admin.headers).status_code == 404

    assert client.patch(f"/api/users/{admin.id}", json={"role": "operator"}, headers=admin.headers).status_code == 409
    assert client.patch(f"/api/users/{admin.id}", json={"is_active": False}, headers=admin.headers).status_code == 409
    assert client.patch(f"/api/users/{admin.id}", json={"full_name": "Можно менять имя"}, headers=admin.headers).status_code == 200

    emails = [u["email"] for u in client.get("/api/users", headers=admin.headers).json()]
    assert new_email in emails
    page = client.get("/api/audit", params={"action": "user_created", "user_id": admin.id}, headers=admin.headers).json()
    assert page["total"] == 1 and page["items"][0]["details"]["email"] == new_email
    upd = client.get("/api/audit", params={"action": "user_updated", "user_id": admin.id}, headers=admin.headers).json()
    assert any(i["details"].get("password_reset") for i in upd["items"])
    assert "Resetpass456" not in str(upd)  # пароль в журнал не попадает


def test_change_password(make_user):
    u = make_user("manager")
    url = "/api/auth/change-password"
    assert client.post(url, json={"current_password": "Wrong-Passw0rd", "new_password": "Brandnew123"}, headers=u.headers).status_code == 400
    assert client.post(url, json={"current_password": PW, "new_password": "weak"}, headers=u.headers).status_code == 422
    assert client.post(url, json={"current_password": PW, "new_password": "Brandnew123"}, headers=u.headers).status_code == 204
    assert login(u.email, PW).status_code == 401 and login(u.email, "Brandnew123").status_code == 200
    assert len(audit("password_changed", user_id=u.id)) == 1


def test_audit_is_admin_only_and_paged(make_user):
    admin, op = make_user("admin"), make_user("operator")
    assert client.get("/api/audit", headers=op.headers).status_code == 403
    login(op.email); login(op.email, "Wrong-Passw0rd")
    j = client.get("/api/audit", params={"user_id": op.id, "limit": 1}, headers=admin.headers).json()
    assert j["total"] >= 1 and len(j["items"]) == 1 and j["items"][0]["user_email"] == op.email
    assert client.get("/api/audit", params={"limit": 500}, headers=admin.headers).status_code == 422
