"""Автоанализ нового обращения: категория, уверенность, срочность, признак ручной проверки."""
import logging
import os
import re
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
# Правила передачи оператору (эксперимент Э7, ml/threshold_analysis.py):
# на тестовой выборке принимается 99,6 % обращений, а расплывчатые тексты отсеиваются
CONFIDENCE_THRESHOLD = 0.7   # ниже этой уверенности категория не назначается
MIN_KNOWN_WORDS = 3          # знакомых модели слов в тексте, не меньше
MIN_KNOWN_SHARE = 0.7        # доля знакомых слов, не меньше
_TOKEN = re.compile(r"(?u)\b\w\w+\b")
REASONS = {
    "no_model": "модель категорий недоступна",
    "analysis_error": "ошибка классификации",
    "unfamiliar_text": "текст не похож на типовые обращения",
    "low_confidence": "низкая уверенность модели",
}

_UNSET = object()
_state = {"model": _UNSET}


@dataclass
class Analysis:
    category_code: str | None
    confidence: float | None
    urgency: int
    needs_review: bool
    reason: str | None = None


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


def _vocabulary(model) -> set[str] | None:
    """Однословные термины, известные модели; None, если модель их не хранит."""
    try:
        word = dict(model.named_steps["tfidf"].transformer_list)["word"]
        return {t for t in word.vocabulary_ if " " not in t}
    except Exception:
        return None


def _familiar(model, body: str) -> bool:
    vocab = _vocabulary(model)
    if vocab is None:
        return True
    tokens = _TOKEN.findall(body.lower())
    known = sum(t in vocab for t in tokens)
    return known >= MIN_KNOWN_WORDS and known / max(len(tokens), 1) >= MIN_KNOWN_SHARE


def analyze(body: str) -> Analysis:
    urgency = urgency_level(body)
    model = load_model()
    if model is None:
        return Analysis(None, None, urgency, True, "no_model")
    try:
        probs = model.predict_proba([body])[0]
        best = max(range(len(probs)), key=lambda i: probs[i])
        code, confidence = str(model.classes_[best]), float(probs[best])
    except Exception:
        log.warning("Ошибка классификации", exc_info=True)
        return Analysis(None, None, urgency, True, "analysis_error")
    if not _familiar(model, body):
        return Analysis(code, confidence, urgency, True, "unfamiliar_text")
    if confidence < CONFIDENCE_THRESHOLD:
        return Analysis(code, confidence, urgency, True, "low_confidence")
    return Analysis(code, confidence, urgency, False)


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
            if result.needs_review:
                session.execute(
                    text(
                        "INSERT INTO appeal_comments (appeal_id, author_id, body, is_internal) "
                        "VALUES (:i, NULL, :b, TRUE)"
                    ),
                    {"i": appeal_id, "b": "Требуется проверка категории: " + REASONS.get(result.reason, "")},
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
