"""Ручная проверка обращений: подсказка модели, фильтр, смена категории. Нужна тестовая база."""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def engine():
    from app.db import engine
    return engine


@pytest.fixture
def categories(engine):
    """В тестовой базе категорий может не быть: создаём нужные и убираем только свои."""
    added = []
    with engine.begin() as c:
        for code, name in (("roads", "Дороги и ямы"), ("garbage", "Мусор")):
            cid = c.execute(
                text("INSERT INTO categories (code, name_ru) VALUES (:c, :n) "
                     "ON CONFLICT (code) DO NOTHING RETURNING id"),
                {"c": code, "n": name},
            ).scalar()
            if cid:
                added.append(cid)
    yield
    with engine.begin() as c:
        c.execute(text("DELETE FROM categories WHERE id = ANY(:ids)"), {"ids": added})


@pytest.fixture
def appeal(engine, make_user, categories):
    """Фабрика обращений; удаляются раньше пользователей и категорий."""
    ids = []

    def make(needs_review=True, category=None, prediction=None):
        with engine.begin() as c:
            cat_id = None
            if category:
                cat_id = c.execute(text("SELECT id FROM categories WHERE code = :c"), {"c": category}).scalar_one()
            appeal_id = c.execute(
                text(
                    "INSERT INTO appeals (text, created_at, needs_review, category_id, status) "
                    "VALUES ('Тестовое обращение на проверку', now(), :r, :cat, 'new') RETURNING id"
                ),
                {"r": needs_review, "cat": cat_id},
            ).scalar_one()
            ids.append(appeal_id)
            if prediction:
                code, conf = prediction
                c.execute(
                    text(
                        "INSERT INTO appeal_predictions (appeal_id, predicted_category_id, confidence, urgency) "
                        "SELECT :a, id, :p, 1 FROM categories WHERE code = :c"
                    ),
                    {"a": appeal_id, "p": conf, "c": code},
                )
        return appeal_id

    yield make
    with engine.begin() as c:
        for appeal_id in ids:
            c.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": appeal_id})


def test_card_has_review_flag_and_suggestion(client, appeal, make_user):
    user = make_user("operator")
    appeal_id = appeal(prediction=("roads", 0.41))
    card = client.get(f"/api/appeals/{appeal_id}", headers=user.headers).json()
    assert card["needs_review"] is True
    assert card["suggestion"]["category"] == "roads"
    assert card["suggestion"]["confidence"] == pytest.approx(0.41, abs=1e-3)


def test_card_without_prediction_has_no_suggestion(client, appeal, make_user):
    user = make_user("operator")
    card = client.get(f"/api/appeals/{appeal(needs_review=False)}", headers=user.headers).json()
    assert card["needs_review"] is False and card["suggestion"] is None


def test_review_filter_and_counter(client, appeal, make_user):
    user = make_user("operator")
    flagged = appeal()
    normal = appeal(needs_review=False)
    data = client.get("/api/cases?review=true&limit=200", headers=user.headers).json()
    ids = {i["id"] for i in data["items"]}
    assert flagged in ids and normal not in ids
    assert all(i["needs_review"] for i in data["items"])
    assert data["review_count"] >= 1
    everything = client.get("/api/cases?limit=200", headers=user.headers).json()
    assert "review_count" in everything


def test_operator_sets_category_and_clears_flag(client, appeal, make_user):
    user = make_user("operator")
    appeal_id = appeal(prediction=("roads", 0.41))
    r = client.post(f"/api/appeals/{appeal_id}/category", json={"category_code": "roads"}, headers=user.headers)
    assert r.status_code == 200
    card = r.json()
    assert card["category"] == "roads" and card["needs_review"] is False
    assert any("Категория" in c["body"] for c in card["comments"])


def test_operator_can_change_category(client, appeal, make_user):
    user = make_user("manager")
    appeal_id = appeal(needs_review=False, category="roads")
    r = client.post(f"/api/appeals/{appeal_id}/category", json={"category_code": "garbage"}, headers=user.headers)
    assert r.status_code == 200 and r.json()["category"] == "garbage"
    again = client.post(f"/api/appeals/{appeal_id}/category", json={"category_code": "garbage"}, headers=user.headers)
    assert again.status_code == 409


def test_unknown_category_rejected(client, appeal, make_user):
    user = make_user("operator")
    r = client.post(f"/api/appeals/{appeal()}/category", json={"category_code": "nope"}, headers=user.headers)
    assert r.status_code == 422


@pytest.mark.parametrize("role", ["analyst", "executor"])
def test_other_roles_cannot_set_category(client, appeal, make_user, role):
    user = make_user(role)
    r = client.post(f"/api/appeals/{appeal()}/category", json={"category_code": "roads"}, headers=user.headers)
    assert r.status_code == 403


def test_category_requires_login(client, appeal):
    assert client.post(f"/api/appeals/{appeal()}/category", json={"category_code": "roads"}).status_code == 401
