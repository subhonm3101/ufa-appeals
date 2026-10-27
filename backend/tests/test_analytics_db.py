"""Тесты аналитики на настоящей базе (только при заданной APPEALS_TEST_DATABASE_URL).

Данные теста лежат в марте 2010 года, где реальных обращений нет, поэтому результаты
не зависят от содержимого базы. После теста удаляются только записи PYTEST-*."""
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

CSV = """external_id,text,created_at,district,category,lat,lon
PYTEST-A1,Прошлый период 1,2010-03-02 10:00,Пайтест-район,pytest_cat,,
PYTEST-A2,Прошлый период 2,2010-03-03 10:00,Пайтест-район,pytest_cat,,
PYTEST-B1,Поздно вечером,2010-03-08T23:30+05:00,Пайтест-район,pytest_cat,54.7,55.9
PYTEST-B2,Сразу после полуночи,2010-03-09T00:10+05:00,Пайтест-район,pytest_cat,,
PYTEST-B3,Днём,2010-03-10 12:00,Пайтест-район,pytest_cat,54.8,56.0
PYTEST-B4,Днём ещё одно,2010-03-10 13:00,Пайтест-район,pytest_cat,,
"""


@pytest.fixture(autouse=True)
def data(make_user):
    client.headers.update(make_user("admin").headers)
    with engine.begin() as c:
        c.execute(text("INSERT INTO categories (code, name_ru) VALUES ('pytest_cat','Тестовая категория') ON CONFLICT (code) DO NOTHING"))
        if not c.execute(text("SELECT 1 FROM districts WHERE name='Пайтест-район'")).first():
            c.execute(text("INSERT INTO districts (name) VALUES ('Пайтест-район')"))
    r = client.post("/api/import", files={"file": ("pytest_analytics.csv", CSV.encode("utf-8"), "text/csv")})
    assert r.json()["inserted"] == 6, r.text
    yield
    with engine.begin() as c:
        c.execute(text("DELETE FROM appeals WHERE external_id LIKE 'PYTEST-%'"))
        c.execute(text("DELETE FROM import_batches WHERE filename LIKE 'pytest_%'"))
        c.execute(text("DELETE FROM categories WHERE code='pytest_cat'"))
        c.execute(text("DELETE FROM districts WHERE name='Пайтест-район'"))
    client.headers.pop("Authorization", None)


def _series(**params):
    base = {"category": "pytest_cat", "district": "Пайтест-район"}
    return client.get("/api/analytics/timeseries", params={**base, **params}).json()


def test_daily_series_fills_gaps_and_uses_ufa_time():
    j = _series(date_from="2010-03-08", date_to="2010-03-14")
    counts = [p["count"] for p in j["points"]]
    # 00:10 по Уфе 9 марта это 19:10 UTC 8 марта: в ряд по местному времени оно попадает на 9-е
    assert counts == [1, 1, 2, 0, 0, 0, 0]
    assert j["total"] == 4 and j["points"][0]["period"] == "2010-03-08"


def test_week_and_month_granularity():
    weeks = _series(date_from="2010-03-01", date_to="2010-03-14", granularity="week")
    assert [(p["period"], p["count"]) for p in weeks["points"]] == [("2010-03-01", 2), ("2010-03-08", 4)]
    month = _series(date_from="2010-03-01", date_to="2010-03-14", granularity="month")
    assert [(p["period"], p["count"]) for p in month["points"]] == [("2010-03-01", 6)]


def test_summary_compares_with_previous_period():
    j = client.get("/api/analytics/summary", params={"date_from": "2010-03-08", "date_to": "2010-03-14"}).json()
    assert (j["total"], j["prev_total"], j["change_pct"], j["days"]) == (4, 2, 100.0, 7)
    assert (j["prev_date_from"], j["prev_date_to"]) == ("2010-03-01", "2010-03-07")
    cat = next(x for x in j["by_category"] if x["code"] == "pytest_cat")
    assert (cat["count"], cat["prev_count"], cat["change_pct"], cat["share"]) == (4, 2, 100.0, 1.0)
    dist = next(x for x in j["by_district"] if x["name"] == "Пайтест-район")
    assert (dist["count"], dist["prev_count"]) == (4, 2)


def test_summary_empty_period():
    j = client.get("/api/analytics/summary", params={"date_from": "2011-01-01", "date_to": "2011-01-07"}).json()
    assert (j["total"], j["prev_total"], j["change_pct"], j["per_day"]) == (0, 0, None, 0.0)


def test_heatmap_cell():
    j = client.get("/api/analytics/heatmap", params={"date_from": "2010-03-08", "date_to": "2010-03-14"}).json()
    assert j["cells"] == [{"category": "pytest_cat", "district": "Пайтест-район", "count": 4}]
    assert "pytest_cat" in [c["code"] for c in j["categories"]] and "Пайтест-район" in j["districts"]


def test_points_only_with_coordinates():
    j = client.get("/api/analytics/points", params={"date_from": "2010-03-01", "date_to": "2010-03-31", "category": "pytest_cat"}).json()
    assert j["total"] == 2 and [i["lat"] for i in j["items"]] == [54.8, 54.7]  # свежие первыми


def test_unknown_category_and_district_404():
    assert client.get("/api/analytics/timeseries", params={"category": "нет_такой"}).status_code == 404
    assert client.get("/api/analytics/points", params={"district": "Марс"}).status_code == 404
