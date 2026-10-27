"""Интеграционные тесты API с настоящей базой. Запускаются только если задана
APPEALS_TEST_DATABASE_URL. Тесты создают и удаляют ТОЛЬКО свои записи (external_id PYTEST-*)."""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="не задана APPEALS_TEST_DATABASE_URL",
)

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
CSV = "external_id,text,created_at,district,category\n{rows}"


@pytest.fixture(autouse=True)
def clean(make_user):
    client.headers.update(make_user("admin").headers)
    with engine.begin() as c:
        c.execute(text("INSERT INTO categories (code, name_ru) VALUES ('pytest_cat','Тестовая категория') ON CONFLICT (code) DO NOTHING"))
        if not c.execute(text("SELECT 1 FROM districts WHERE name='Пайтест-район'")).first():
            c.execute(text("INSERT INTO districts (name) VALUES ('Пайтест-район')"))
    yield
    with engine.begin() as c:
        c.execute(text("DELETE FROM appeals WHERE external_id LIKE 'PYTEST-%'"))
        c.execute(text("DELETE FROM import_batches WHERE filename LIKE 'pytest_%'"))
        c.execute(text("DELETE FROM categories WHERE code='pytest_cat'"))
        c.execute(text("DELETE FROM districts WHERE name='Пайтест-район'"))
    client.headers.pop("Authorization", None)


def _upload(body: str, name="pytest_a.csv", **params):
    return client.post("/api/import", params=params, files={"file": (name, body.encode("utf-8"), "text/csv")})


def test_import_then_repeat_is_idempotent():
    body = CSV.format(rows=(
        "PYTEST-1,Яма у дома,2026-10-01 10:00,Пайтест-район,pytest_cat\n"
        "PYTEST-2,Нет света,2026-10-02 11:00,Пайтест-район,Тестовая категория\n"
        "PYTEST-3,Плохая строка,вчера,Пайтест-район,pytest_cat\n"
    ))
    r = _upload(body)
    assert r.status_code == 200
    j = r.json()
    assert (j["rows_total"], j["inserted"], j["rows_failed"]) == (3, 2, 1) and j["batch_id"]

    again = _upload(body).json()
    assert again["inserted"] == 0 and again["duplicates_skipped"] == 2 and again["batch_id"] is None


def test_dry_run_writes_nothing():
    body = CSV.format(rows="PYTEST-9,Яма,2026-10-01 10:00,Пайтест-район,pytest_cat\n")
    j = _upload(body, dry_run="true").json()
    assert j["new_rows"] == 1 and j["inserted"] == 0
    page = client.get("/api/appeals", params={"q": "Яма", "category": "pytest_cat"}).json()
    assert page["total"] == 0


def test_list_filters_and_paging():
    rows = "".join(f"PYTEST-{i},Тестовое обращение номер {i},2026-10-0{i} 10:00,Пайтест-район,pytest_cat\n" for i in range(1, 6))
    assert _upload(CSV.format(rows=rows)).json()["inserted"] == 5
    p = client.get("/api/appeals", params={"category": "pytest_cat", "limit": 2}).json()
    assert p["total"] == 5 and len(p["items"]) == 2 and p["items"][0]["external_id"] == "PYTEST-5"
    p = client.get("/api/appeals", params={"category": "pytest_cat", "date_from": "2026-10-02", "date_to": "2026-10-03"}).json()
    assert p["total"] == 2
    p = client.get("/api/appeals", params={"category": "pytest_cat", "q": "номер 4"}).json()
    assert p["total"] == 1
    p = client.get("/api/appeals", params={"q": "100%"}).json()  # символ % не должен работать как маска
    assert p["total"] == 0


def test_bad_file_returns_422():
    r = client.post("/api/import", files={"file": ("pytest_x.csv", b"foo,bar\n1,2\n", "text/csv")})
    assert r.status_code == 422 and "обязательных колонок" in r.json()["detail"]
