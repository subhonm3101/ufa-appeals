"""Очередь приоритетов отдаёт координаты кластера (нужны карте). Нужна тестовая база."""
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
def seeded_cluster():
    from sqlalchemy import text

    from app.db import engine

    tag = uuid.uuid4().hex[:8]
    with engine.begin() as c:
        cat = c.execute(text(
            "INSERT INTO categories (code, name_ru) VALUES (:c, 'Тестовая') RETURNING id"),
            {"c": f"pytest_{tag}"}).scalar_one()
        dist = c.execute(text(
            "INSERT INTO districts (name) VALUES (:n) RETURNING id"),
            {"n": f"pytest_{tag}"}).scalar_one()
        cluster = c.execute(text(
            "INSERT INTO clusters (category_id, district_id, centroid_lat, centroid_lon, "
            "first_seen, last_seen) VALUES (:c, :d, 54.7123, 55.9456, now(), now()) RETURNING id"),
            {"c": cat, "d": dist}).scalar_one()
        c.execute(text(
            "INSERT INTO priority_scores (cluster_id, score, factors, method, as_of) "
            "VALUES (:cl, 42.5, CAST(:f AS jsonb), 'rules_v1', '2099-01-01 12:00+00')"),
            {"cl": cluster, "f": json.dumps({"components": {}})})
    yield {"category": f"pytest_{tag}", "cluster_id": cluster}
    with engine.begin() as c:
        c.execute(text("DELETE FROM priority_scores WHERE cluster_id = :x"), {"x": cluster})
        c.execute(text("DELETE FROM clusters WHERE id = :x"), {"x": cluster})
        c.execute(text("DELETE FROM districts WHERE id = :x"), {"x": dist})
        c.execute(text("DELETE FROM categories WHERE id = :x"), {"x": cat})


def test_queue_contains_cluster_coordinates(client, make_user, seeded_cluster):
    user = make_user("analyst")
    r = client.get("/api/priority/queue", params={"category": seeded_cluster["category"]},
                   headers=user.headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["cluster_id"] == seeded_cluster["cluster_id"]
    assert item["centroid_lat"] == pytest.approx(54.7123)
    assert item["centroid_lon"] == pytest.approx(55.9456)
