"""Автоанализ без базы: подставляем свою модель."""
import pytest

from app.services import autoanalysis


class FakeModel:
    classes_ = ["garbage", "roads"]

    def __init__(self, probs):
        self.probs = probs

    def predict_proba(self, texts):
        return [self.probs for _ in texts]


@pytest.fixture(autouse=True)
def _reset():
    yield
    autoanalysis.reset()


def test_confident_prediction():
    autoanalysis.set_model(FakeModel([0.1, 0.9]))
    a = autoanalysis.analyze("Яма на дороге")
    assert (a.category_code, a.needs_review) == ("roads", False)
    assert a.confidence == pytest.approx(0.9)


def test_low_confidence_goes_to_operator():
    autoanalysis.set_model(FakeModel([0.45, 0.55 - 0.01]))
    a = autoanalysis.analyze("Что-то непонятное")
    assert a.needs_review is True and a.category_code == "roads"


def test_threshold_is_inclusive():
    autoanalysis.set_model(FakeModel([0.45, autoanalysis.CONFIDENCE_THRESHOLD]))
    assert autoanalysis.analyze("текст").needs_review is False


def test_no_model_means_review():
    autoanalysis.set_model(None)
    a = autoanalysis.analyze("Яма на дороге")
    assert a.category_code is None and a.needs_review is True


def test_broken_model_does_not_raise():
    class Broken:
        classes_ = ["a"]

        def predict_proba(self, texts):
            raise RuntimeError("boom")

    autoanalysis.set_model(Broken())
    assert autoanalysis.analyze("текст").needs_review is True


def test_missing_model_file_is_handled(monkeypatch, tmp_path):
    monkeypatch.setattr(autoanalysis, "MODEL_PATH", tmp_path / "none.joblib")
    autoanalysis.reset()
    assert autoanalysis.load_model() is None


class VocabModel(FakeModel):
    """Модель с «словарём», как у настоящего конвейера TF-IDF."""

    class _Word:
        vocabulary_ = {"яма": 0, "на": 1, "дороге": 2, "ленина": 3, "яма на": 4}

    class _Tfidf:
        transformer_list = [("word", None)]

    def __init__(self, probs):
        super().__init__(probs)
        tfidf = self._Tfidf()
        tfidf.transformer_list = [("word", self._Word())]
        self.named_steps = {"tfidf": tfidf}


def test_unfamiliar_text_goes_to_review_even_if_confident():
    autoanalysis.set_model(VocabModel([0.01, 0.99]))
    a = autoanalysis.analyze("Сделайте уже что-нибудь наконец")
    assert a.needs_review is True and a.reason == "unfamiliar_text"
    assert a.category_code == "roads"


def test_familiar_text_is_accepted():
    autoanalysis.set_model(VocabModel([0.01, 0.99]))
    a = autoanalysis.analyze("Яма на дороге на Ленина")
    assert a.needs_review is False and a.reason is None


def test_reasons_are_reported():
    autoanalysis.set_model(FakeModel([0.5, 0.45]))
    assert autoanalysis.analyze("текст").reason == "low_confidence"
    autoanalysis.set_model(None)
    assert autoanalysis.analyze("текст").reason == "no_model"
