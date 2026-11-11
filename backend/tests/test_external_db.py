"""Внешний API и ключи доступа (шаг 11.6). Нужна тестовая база."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

BODY = "На перекрёстке не работает светофор, водители едут не глядя."


@pytest.fixture
def client():
    from app.api import external
    from app.main import app

    for lim in (external.key_limiter, external.bad_key_limiter):
        lim.reset()
    yield TestClient(app)
    for lim in (external.key_limiter, external.bad_key_limiter):
        lim.reset()


@pytest.fixture
def engine():
    from app.db import engine
    return engine


@pytest.fixture
def admin(make_user, engine):
    """Администратор; ключи и их обращения удаляются до пользователя."""
    user = make_user("admin")
    yield user
    with engine.begin() as c:
        c.execute(text("DELETE FROM appeals WHERE external_id LIKE :p"), {"p": "k%:pytest-%"})
        c.execute(text("DELETE FROM api_keys WHERE name LIKE :p"), {"p": "pytest-%"})


def new_key(client, admin, name=None):
    r = client.post("/api/api-keys", json={"name": name or f"pytest-{uuid.uuid4().hex[:6]}"}, headers=admin.headers)
    assert r.status_code == 201, r.text
    return r.json()


def hdr(key):
    return {"X-API-Key": key}


def ext_id():
    return f"pytest-{uuid.uuid4().hex[:10]}"


def test_only_admin_manages_keys(client, make_user):
    for role in ("operator", "analyst", "manager", "executor"):
        u = make_user(role)
        assert client.get("/api/api-keys", headers=u.headers).status_code == 403
        assert client.post("/api/api-keys", json={"name": "pytest-x"}, headers=u.headers).status_code == 403
    assert client.get("/api/api-keys").status_code == 401


def test_key_is_shown_once_and_stored_hashed(client, engine, admin):
    k = new_key(client, admin)
    assert k["key"].startswith("ufa_")
    listing = client.get("/api/api-keys", headers=admin.headers).json()
    mine = next(i for i in listing if i["id"] == k["id"])
    assert "key" not in mine and "key_hash" not in mine
    assert k["key"] not in str(listing)
    with engine.connect() as c:
        stored = c.execute(text("SELECT key_hash FROM api_keys WHERE id = :i"), {"i": k["id"]}).scalar_one()
    assert stored != k["key"] and len(stored) == 64


def test_submit_and_status(client, admin):
    k = new_key(client, admin)
    eid = ext_id()
    r = client.post("/api/external/appeals", json={"text": BODY, "external_id": eid}, headers=hdr(k["key"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True and body["external_id"] == eid and body["public_number"].startswith("UFA-")
    s = client.get(f"/api/external/appeals/{body['public_number']}", headers=hdr(k["key"]))
    assert s.status_code == 200
    assert s.json()["external_id"] == eid and s.json()["status"] == "new"


def test_duplicate_external_id_returns_same_appeal(client, admin):
    k = new_key(client, admin)
    eid = ext_id()
    first = client.post("/api/external/appeals", json={"text": BODY, "external_id": eid}, headers=hdr(k["key"])).json()
    second = client.post("/api/external/appeals", json={"text": BODY, "external_id": eid}, headers=hdr(k["key"])).json()
    assert second["public_number"] == first["public_number"] and second["created"] is False


def test_same_external_id_for_different_keys_is_independent(client, admin):
    a, b = new_key(client, admin), new_key(client, admin)
    eid = ext_id()
    ra = client.post("/api/external/appeals", json={"text": BODY, "external_id": eid}, headers=hdr(a["key"])).json()
    rb = client.post("/api/external/appeals", json={"text": BODY, "external_id": eid}, headers=hdr(b["key"])).json()
    assert ra["public_number"] != rb["public_number"] and rb["created"] is True


def test_key_cannot_see_foreign_appeals(client, admin):
    a, b = new_key(client, admin), new_key(client, admin)
    n = client.post("/api/external/appeals", json={"text": BODY, "external_id": ext_id()}, headers=hdr(a["key"])).json()["public_number"]
    assert client.get(f"/api/external/appeals/{n}", headers=hdr(b["key"])).status_code == 404


def test_missing_wrong_and_revoked_key(client, admin):
    payload = {"text": BODY, "external_id": ext_id()}
    assert client.post("/api/external/appeals", json=payload).status_code == 401
    assert client.post("/api/external/appeals", json=payload, headers=hdr("ufa_wrong")).status_code == 401
    k = new_key(client, admin)
    assert client.post("/api/external/appeals", json=payload, headers=hdr(k["key"])).status_code == 200
    assert client.post(f"/api/api-keys/{k['id']}/revoke", headers=admin.headers).status_code == 200
    assert client.post("/api/external/appeals", json=payload, headers=hdr(k["key"])).status_code == 401
    assert client.post("/api/api-keys/999999/revoke", headers=admin.headers).status_code == 404


def test_validation_errors(client, admin):
    k = new_key(client, admin)
    short = client.post("/api/external/appeals", json={"text": "коротко", "external_id": ext_id()}, headers=hdr(k["key"]))
    assert short.status_code == 422
    no_id = client.post("/api/external/appeals", json={"text": BODY}, headers=hdr(k["key"]))
    assert no_id.status_code == 422


def test_bad_key_attempts_are_limited(client):
    from app.api import external
    external.bad_key_limiter.reset()
    codes = [client.get("/api/external/appeals/UFA-2026-000001", headers=hdr("ufa_guess")).status_code for _ in range(32)]
    assert codes[0] == 401 and codes[-1] == 429
