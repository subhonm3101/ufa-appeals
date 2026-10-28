import numpy as np

from ml.compare_models import markdown_table, summarize
from ml.train_tfidf_baseline import SCENARIOS


def make(tf, rb):
    return [{"tfidf": {"macro_f1": a, "accuracy": a}, "rubert": {"macro_f1": b, "accuracy": b}}
            for a, b in zip(tf, rb)]


def test_summarize_values():
    s = summarize(make([0.4, 0.5, 0.6], [0.5, 0.6, 0.55]))
    assert s["tfidf"]["macro_f1"]["mean"] == 0.5
    assert np.isclose(s["tfidf"]["macro_f1"]["std"], 0.1)
    d = s["diff_macro_f1_rubert_minus_tfidf"]
    assert d["rubert_wins"] == 2 and d["seeds"] == 3
    assert d["min"] <= d["mean"] <= d["max"]


def test_single_seed_has_zero_std():
    s = summarize(make([0.5], [0.6]))
    assert s["tfidf"]["macro_f1"]["std"] == 0.0


def test_markdown_has_row_per_scenario():
    summ = {k: summarize(make([0.5, 0.6], [0.6, 0.7])) for k in SCENARIOS}
    t = markdown_table(summ)
    assert t.count("\n") == 1 + len(SCENARIOS)
    assert "2 из 2" in t
