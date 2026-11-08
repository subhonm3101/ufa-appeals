"""Автоанализ при регистрации обращения. Нужна тестовая база."""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import autoanalysis

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

BODY = "На улице Ленина огромная яма на проезжей части, машины повреждают колёса."


class FakeModel:
    classes_ = ["roads", "garbage"]

    def __init__(self, probs):
        self.probs = probs

    def predict_proba(self, texts):
        return [self.probs for _ in texts]


@pytest.fixture
def session():
    from app.db import engine
    with Session(engine) as s:
        yield s


@pytest.fixture
def categories(session):
    """В тестовой базе категорий может не быть: создаём нужные и убираем только свои."""
    added = []
    for code, name in (("roads", "Дороги и ямы"), ("garbage", "Мусор")):
        cid = session.execute(
            text("INSERT INTO categories (code, name_ru) VALUES (:c, :n) "
                 "ON CONFLICT (code) DO NOTHING RETURNING id"),
            {"c": code, "n": name},
        ).scalar()
        if cid:
            added.append(cid)
    session.commit()
    yield
    session.execute(text("DELETE FROM categories WHERE id = ANY(:ids)"), {"ids": added})
    session.commit()


@pytest.fixture
def created(session, categories):
    ids = []
    yield ids
    for i in ids:
        session.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": i})
    session.commit()
    autoanalysis.reset()


def register(session, created):
    from app.services.intake import NewAppeal, register as reg
    r = reg(session, NewAppeal(text=BODY))
    created.append(r.id)
    return r.id


def row(session, appeal_id):
    return session.execute(
        text(
            "SELECT a.needs_review, c.code FROM appeals a "
            "LEFT JOIN categories c ON c.id = a.category_id WHERE a.id = :i"
        ),
        {"i": appeal_id},
    ).one()


def predictions(session, appeal_id):
    return session.execute(
        text(
            "SELECT p.confidence, p.urgency, c.code FROM appeal_predictions p "
            "JOIN categories c ON c.id = p.predicted_category_id WHERE p.appeal_id = :i"
        ),
        {"i": appeal_id},
    ).all()


def test_confident_prediction_sets_category(session, created):
    autoanalysis.set_model(FakeModel([0.9, 0.1]))
    i = register(session, created)
    got = row(session, i)
    assert (got.needs_review, got.code) == (False, "roads")
    preds = predictions(session, i)
    assert len(preds) == 1 and preds[0].code == "roads"
    assert preds[0].confidence == pytest.approx(0.9, abs=1e-3)


def test_low_confidence_keeps_category_empty_and_flags_review(session, created):
    autoanalysis.set_model(FakeModel([0.4, 0.3]))
    i = register(session, created)
    got = row(session, i)
    assert (got.needs_review, got.code) == (True, None)
    assert [p.code for p in predictions(session, i)] == ["roads"]


def test_without_model_appeal_is_still_registered(session, created):
    autoanalysis.set_model(None)
    i = register(session, created)
    got = row(session, i)
    assert (got.needs_review, got.code) == (True, None)
    assert predictions(session, i) == []


def test_real_model_if_available(session, created):
    if not autoanalysis.MODEL_PATH.exists():
        pytest.skip("файл модели не найден")
    autoanalysis.reset()
    i = register(session, created)
    got = row(session, i)
    assert got.code == "roads" or got.needs_review


def test_predictions_are_deleted_with_appeal(session, categories):
    autoanalysis.set_model(FakeModel([0.9, 0.1]))
    from app.services.intake import NewAppeal, register as reg
    r = reg(session, NewAppeal(text=BODY))
    assert len(predictions(session, r.id)) == 1
    session.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": r.id})
    session.commit()
    assert predictions(session, r.id) == []
    autoanalysis.reset()
