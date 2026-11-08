"""Автоанализ нового обращения: категория, уверенность, срочность, признак ручной проверки."""
import logging
import os
import warnings
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from .priority_features import urgency_level

log = logging.getLogger(__name__)

MODEL_PATH = Path(
    os.environ.get("APPEALS_CATEGORY_MODEL")
    or Path(__file__).resolve().parents[3] / "ml" / "models" / "tfidf_logreg_A_grouped.joblib"
)
# Ниже этой уверенности категория не назначается, обращение уходит оператору
CONFIDENCE_THRESHOLD = 0.55

_UNSET = object()
_state = {"model": _UNSET}


@dataclass
class Analysis:
    category_code: str | None
    confidence: float | None
    urgency: int
    needs_review: bool


def set_model(model) -> None:
    """Подменяет модель (для тестов); None означает «модели нет»."""
    _state["model"] = model


def reset() -> None:
    _state["model"] = _UNSET


def load_model():
    """Загружает модель один раз; при любой ошибке возвращает None (приём не должен ломаться)."""
    if _state["model"] is _UNSET:
        try:
            import joblib

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _state["model"] = joblib.load(MODEL_PATH)
        except Exception:
            log.warning("Модель категорий не загружена: %s", MODEL_PATH, exc_info=True)
            _state["model"] = None
    return _state["model"]


def analyze(body: str) -> Analysis:
    urgency = urgency_level(body)
    model = load_model()
    if model is None:
        return Analysis(None, None, urgency, True)
    try:
        probs = model.predict_proba([body])[0]
        best = max(range(len(probs)), key=lambda i: probs[i])
        code, confidence = str(model.classes_[best]), float(probs[best])
    except Exception:
        log.warning("Ошибка классификации", exc_info=True)
        return Analysis(None, None, urgency, True)
    return Analysis(code, confidence, urgency, confidence < CONFIDENCE_THRESHOLD)


def _model_id(session: Session) -> int | None:
    try:
        with session.begin_nested():
            return session.execute(
                text("SELECT id FROM ml_models WHERE name ILIKE '%tfidf%' ORDER BY id DESC LIMIT 1")
            ).scalar()
    except Exception:
        return None


def apply(session: Session, appeal_id: int, body: str) -> Analysis:
    """Анализирует текст и записывает результат в текущую транзакцию (фиксирует вызывающий код).

    Сбой анализа не прерывает регистрацию: обращение просто уходит на ручную проверку.
    """
    result = analyze(body)
    try:
        with session.begin_nested():
            category_id = None
            if result.category_code:
                category_id = session.execute(
                    text("SELECT id FROM categories WHERE code = :c"), {"c": result.category_code}
                ).scalar()
            session.execute(
                text(
                    "UPDATE appeals SET needs_review = CAST(:r AS boolean), "
                    "category_id = CASE WHEN CAST(:r AS boolean) THEN category_id ELSE CAST(:c AS integer) END WHERE id = :i"
                ),
                {"r": result.needs_review, "c": category_id, "i": appeal_id},
            )
            if category_id is not None:
                session.execute(
                    text(
                        "INSERT INTO appeal_predictions "
                        "(appeal_id, model_id, predicted_category_id, confidence, urgency) "
                        "VALUES (:a, :m, :c, :p, :u)"
                    ),
                    {"a": appeal_id, "m": _model_id(session), "c": category_id,
                     "p": result.confidence, "u": float(result.urgency)},
                )
    except Exception:
        log.exception("Не удалось сохранить результат автоанализа обращения %s", appeal_id)
        session.execute(text("UPDATE appeals SET needs_review = TRUE WHERE id = :i"), {"i": appeal_id})
        result.needs_review = True
    return result
