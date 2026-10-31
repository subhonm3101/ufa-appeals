"""Тесты API прогноза и аномалий. Нужна тестовая база (APPEALS_TEST_DATABASE_URL)."""
import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def seeded():
    """Свои категория, район, модель, прогнозы и аномалии; всё удаляется после теста."""
    from sqlalchemy import text

    from app.db import engine

    tag = uuid.uuid4().hex[:8]
    made_at = "2099-01-01T00:00:00+00"  # новее любых реальных прогнозов
    with engine.begin() as c:
        cat = c.execute(text(
            "INSERT INTO categories (code, name_ru) VALUES (:c, 'Тестовая') RETURNING id"),
            {"c": f"pytest_{tag}"}).scalar_one()
        dist = c.execute(text(
            "INSERT INTO districts (name) VALUES (:n) RETURNING id"),
            {"n": f"pytest_{tag}"}).scalar_one()
        model = c.execute(text(
            "INSERT INTO ml_models (task, name, version, metrics, trained_at) "
            "VALUES ('forecast', 'pytest_model', :v, CAST(:m AS jsonb), now()) RETURNING id"),
            {"v": tag, "m": json.dumps({"city_wape_pct": 1.0})}).scalar_one()
        ins = text(
            "INSERT INTO forecasts (model_id, category_id, district_id, target_date, "
            "value, lower, upper, granularity, made_at) "
            "VALUES (:m, :c, NULL, :t, :v, :lo, :hi, 'week', :ts)")
        for i in range(4):  # уровень города
            c.execute(text(
                "INSERT INTO forecasts (model_id, category_id, district_id, target_date, "
                "value, lower, upper, granularity, made_at) "
                "VALUES (:m, NULL, NULL, :t, :v, :lo, :hi, 'week', :ts)"),
                {"m": model, "t": f"2099-02-{i + 1:02d}", "v": 100 + i,
                 "lo": 90 + i, "hi": 110 + i, "ts": made_at})
        for i in range(2):  # уровень категории
            c.execute(ins, {"m": model, "c": cat, "t": f"2099-02-{i + 1:02d}",
                            "v": 10 + i, "lo": 5, "hi": 15, "ts": made_at})
        for day in ("2030-01-01", "2030-01-02", "2030-01-10"):  # два события
            c.execute(text(
                "INSERT INTO anomalies (category_id, district_id, day, observed, expected, score) "
                "VALUES (:c, :d, :day, 8, 1.5, 4.2)"), {"c": cat, "d": dist, "day": day})
    yield {"category": f"pytest_{tag}", "district": f"pytest_{tag}"}
    with engine.begin() as c:
        c.execute(text("DELETE FROM forecasts WHERE model_id = :m"), {"m": model})
        c.execute(text("DELETE FROM ml_models WHERE id = :m"), {"m": model})
        c.execute(text("DELETE FROM anomalies WHERE category_id = :c"), {"c": cat})
        c.execute(text("DELETE FROM districts WHERE id = :d"), {"d": dist})
        c.execute(text("DELETE FROM categories WHERE id = :c"), {"c": cat})


URLS = ["/api/forecast", "/api/anomalies"]


@pytest.mark.parametrize("url", URLS)
def test_requires_login(client, url):
    assert client.get(url).status_code == 401


@pytest.mark.parametrize("url", URLS)
def test_operator_forbidden(client, make_user, url):
    user = make_user("operator")
    assert client.get(url, headers=user.headers).status_code == 403


@pytest.mark.parametrize("role", ["analyst", "manager", "admin"])
def test_roles_can_read_forecast(client, make_user, seeded, role):
    user = make_user(role)
    r = client.get("/api/forecast", params={"granularity": "week"}, headers=user.headers)
    assert r.status_code == 200


def test_forecast_city_level(client, make_user, seeded):
    user = make_user("analyst")
    body = client.get("/api/forecast", params={"granularity": "week"},
                      headers=user.headers).json()
    assert body["level"] == "city"
    assert body["model"]["name"] == "pytest_model"
    assert len(body["items"]) == 4
    first = body["items"][0]
    assert first["lower"] <= first["value"] <= first["upper"]


def test_forecast_category_level(client, make_user, seeded):
    user = make_user("analyst")
    body = client.get("/api/forecast",
                      params={"granularity": "week", "category": seeded["category"]},
                      headers=user.headers).json()
    assert body["level"] == "category"
    assert len(body["items"]) == 2


def test_forecast_pair_not_published(client, make_user, seeded):
    user = make_user("analyst")
    r = client.get("/api/forecast",
                   params={"category": seeded["category"], "district": seeded["district"]},
                   headers=user.headers)
    assert r.status_code == 422


def test_forecast_unknown_category(client, make_user):
    user = make_user("analyst")
    r = client.get("/api/forecast", params={"category": "no_such_category"},
                   headers=user.headers)
    assert r.status_code == 404


def test_forecast_bad_granularity(client, make_user):
    user = make_user("analyst")
    r = client.get("/api/forecast", params={"granularity": "month"}, headers=user.headers)
    assert r.status_code == 422


def test_anomalies_events_merged(client, make_user, seeded):
    user = make_user("manager")
    body = client.get("/api/anomalies", params={"category": seeded["category"]},
                      headers=user.headers).json()
    assert body["total"] == 2
    newest, oldest = body["items"]
    assert newest["start"] == "2030-01-10" and newest["days"] == 1
    assert oldest["start"] == "2030-01-01" and oldest["end"] == "2030-01-02"
    assert oldest["days"] == 2 and oldest["peak"] == 8


def test_anomalies_date_filter(client, make_user, seeded):
    user = make_user("manager")
    body = client.get("/api/anomalies",
                      params={"category": seeded["category"], "date_from": "2030-01-05"},
                      headers=user.headers).json()
    assert body["total"] == 1
    assert body["items"][0]["start"] == "2030-01-10"


def test_anomalies_district_filter_empty(client, make_user, seeded):
    user = make_user("manager")
    body = client.get("/api/anomalies", params={"district": "no_such_district"},
                      headers=user.headers).json()
    assert body["total"] == 0 and body["items"] == []
