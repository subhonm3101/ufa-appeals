
import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="не задана APPEALS_TEST_DATABASE_URL",
)

from app.main import app
from app.db import engine

client = TestClient(app)


@pytest.fixture
def priority_data():
    """Создаёт изолированные тестовые записи в тестовой базе."""
    suffix = uuid.uuid4().hex[:12]
    code = f"test_{suffix}"
    district_name = f"Тестовый район {suffix}"
    external_id = f"test-{suffix}"
    cluster_id = None
    appeal_id = None

    try:
        with engine.begin() as conn:
            category_id = conn.execute(
                text("""
                    INSERT INTO categories (code, name_ru, base_weight)
                    VALUES (:code, :name, 1.0)
                    RETURNING id
                """),
                {"code": code, "name": f"Тестовая категория {suffix}"},
            ).scalar_one()

            district_id = conn.execute(
                text("""
                    INSERT INTO districts (name)
                    VALUES (:name)
                    RETURNING id
                """),
                {"name": district_name},
            ).scalar_one()

            cluster_id = conn.execute(
                text("""
                    INSERT INTO clusters (
                        category_id, district_id, centroid_lat, centroid_lon,
                        appeals_count, first_seen, last_seen, status
                    )
                    VALUES (
                        :category_id, :district_id, 54.7, 55.9,
                        1, CURRENT_DATE, CURRENT_DATE, 'open'
                    )
                    RETURNING id
                """),
                {
                    "category_id": category_id,
                    "district_id": district_id,
                },
            ).scalar_one()

             
            batch_id = conn.execute(
                text("""
                    INSERT INTO import_batches (
                        filename, source, rows_total, rows_ok, rows_failed
                    )
                    VALUES (:filename, :source, 1, 1, 0)
                    RETURNING id
                """),
                {
                    "filename": f"pytest-{suffix}.csv",
                    "source": "pytest",
                },
            ).scalar_one()

            appeal_id = conn.execute(
                text("""
                    INSERT INTO appeals (
                        batch_id, external_id, text, created_at,
                        district_id, lat, lon, category_id, cluster_id, status
                    )
                    VALUES (
                        :batch_id, :external_id, 'Тестовое обращение',
                        CURRENT_TIMESTAMP, :district_id, 54.7, 55.9,
                        :category_id, :cluster_id, 'new'
                    )
                    RETURNING id
                """),
                {
                    "batch_id": batch_id,
                    "external_id": external_id,
                    "district_id": district_id,
                    "category_id": category_id,
                    "cluster_id": cluster_id,
                },
            ).scalar_one()

            conn.execute(
                text("""
                    INSERT INTO priority_scores (
                        cluster_id, score, factors, calculated_at, method, as_of
                    )
                    VALUES (
                        :cluster_id, 0.95,
                        CAST(:factors AS jsonb), CURRENT_TIMESTAMP,
                        'rules_v1', CURRENT_TIMESTAMP
                    )
                """),
                {
                    "cluster_id": cluster_id,
                    "factors": (
                        '{"components":{"urgency":0.9,"significance":0.8,'
                        '"scale":0.7,"age":0.6,"dynamics":0.5}}'
                    ),
                },
            )

        yield {"cluster_id": cluster_id, "appeal_id": appeal_id}

    finally:
        with engine.begin() as conn:
            if cluster_id is not None:
                conn.execute(
                    text("DELETE FROM priority_scores WHERE cluster_id = :id"),
                    {"id": cluster_id},
                )
                conn.execute(
                    text("DELETE FROM appeals WHERE cluster_id = :id"),
                    {"id": cluster_id},
                )
                conn.execute(
                    text("DELETE FROM clusters WHERE id = :id"),
                    {"id": cluster_id},
                )

            if appeal_id is not None:
                conn.execute(
                    text("DELETE FROM appeals WHERE id = :id"),
                    {"id": appeal_id},
                )

            conn.execute(
                text("DELETE FROM import_batches WHERE filename = :filename"),
                {"filename": f"pytest-{suffix}.csv"},
            )
            conn.execute(
                text("DELETE FROM categories WHERE code = :code"),
                {"code": code},
            )
            conn.execute(
                text("DELETE FROM districts WHERE name = :name"),
                {"name": district_name},
            )




def test_priority_queue_requires_authentication():
    response = client.get("/api/priority/queue")
    assert response.status_code == 401


def test_priority_cluster_details_requires_authentication():
    response = client.get("/api/priority/clusters/1")
    assert response.status_code == 401


def test_priority_queue_returns_rules_v1(make_user, priority_data):
    user = make_user("admin")
    response = client.get(
        "/api/priority/queue",
        params={"limit": 3},
        headers=user.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["method"] == "rules_v1"
    assert body["limit"] == 3
    assert len(body["items"]) <= 3
    assert body["total"] >= len(body["items"])

    scores = [item["score"] for item in body["items"]]
    assert scores == sorted(scores, reverse=True)
    assert any(item["cluster_id"] == priority_data["cluster_id"]
               for item in body["items"])

    for item in body["items"]:
        assert "cluster_id" in item
        assert "components" in item["factors"]
        assert item["category"] is not None


def test_priority_cluster_details_returns_components_and_appeals(
    make_user, priority_data
):
    user = make_user("admin")
    cluster_id = priority_data["cluster_id"]

    response = client.get(
        f"/api/priority/clusters/{cluster_id}",
        headers=user.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == cluster_id
    assert body["score"] == pytest.approx(0.95)
    assert set(body["components"]) == {
        "urgency", "significance", "scale", "age", "dynamics"
    }
    assert any(a["id"] == priority_data["appeal_id"] for a in body["appeals"])


def test_priority_cluster_details_unknown_id_returns_404(make_user):
    user = make_user("admin")
    response = client.get(
        "/api/priority/clusters/2147483647",
        headers=user.headers,
    )
    assert response.status_code == 404
@pytest.mark.parametrize("role", ["operator", "analyst"])
def test_priority_recalculate_forbidden_for_operator_and_analyst(make_user, role):
    user = make_user(role)

    response = client.post(
        "/api/priority/recalculate",
        headers=user.headers,
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize("role", ["admin", "manager"])
def test_priority_recalculate_allowed_for_admin_and_manager(
    make_user, priority_data, role
):
    user = make_user(role)

    response = client.post(
        "/api/priority/recalculate",
        headers=user.headers,
    )

    assert response.status_code == 200, response.text

    body = response.json()
    assert body["method"] == "rules_v1"
    assert body["processed_clusters"] >= 1
