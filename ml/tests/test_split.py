import os
import numpy as np
import pandas as pd
import pytest

from ml.common import (assert_no_group_leak, grouped_split, heldout_subtopic_split,
                       load_dataset, random_split)

DATA = os.environ.get("APPEALS_DATA", os.path.join(os.path.dirname(__file__), "..", "..", "data", "appeals_synthetic.csv"))


def toy(n_problems=300, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    cats = {"a": ["a1", "a2", "a3", "a4"], "b": ["b1", "b2", "b3"], "c": ["c1", "c2"]}
    for p in range(n_problems):
        cat = rng.choice(list(cats))
        sub = rng.choice(cats[cat])
        for k in range(rng.integers(1, 4)):
            rows.append({"external_id": f"E{len(rows)}", "text": f"t{len(rows)}", "category": cat,
                         "problem_id": f"P{p}", "subtopic": sub})
    return pd.DataFrame(rows)


def covers_all(df, s):
    return sorted(np.concatenate([s["train"], s["val"], s["test"]])) == list(range(len(df)))


def test_grouped_no_leak_and_complete():
    df = toy()
    s = grouped_split(df)
    assert_no_group_leak(df, s)
    assert covers_all(df, s)
    assert 0.10 < len(s["test"]) / len(df) < 0.20


def test_grouped_all_classes_in_every_part():
    df = toy()
    s = grouped_split(df)
    for part in s.values():
        assert set(df.iloc[part]["category"]) == set(df["category"])


def test_heldout_subtopics_disjoint():
    df = toy()
    s = heldout_subtopic_split(df)
    assert_no_group_leak(df, s)
    assert covers_all(df, s)
    seen = set(df.iloc[np.concatenate([s["train"], s["val"]])]["subtopic"])
    assert not (seen & set(df.iloc[s["test"]]["subtopic"]))
    for cat in df["category"].unique():  # в обучении есть каждая категория
        assert cat in set(df.iloc[s["train"]]["category"])


def test_split_is_reproducible():
    df = toy()
    assert np.array_equal(grouped_split(df, 5)["test"], grouped_split(df, 5)["test"])
    assert not np.array_equal(grouped_split(df, 5)["test"], grouped_split(df, 6)["test"])


def test_random_split_leaks_groups():
    # сценарий C должен давать утечку: иначе демонстрация теряет смысл
    df = toy()
    with pytest.raises(AssertionError):
        assert_no_group_leak(df, random_split(df))


@pytest.mark.skipif(not os.path.exists(DATA), reason="нет data/appeals_synthetic.csv")
def test_real_dataset_splits():
    df = load_dataset(DATA)
    for fn in (grouped_split, heldout_subtopic_split):
        s = fn(df)
        assert_no_group_leak(df, s)
        assert covers_all(df, s)
