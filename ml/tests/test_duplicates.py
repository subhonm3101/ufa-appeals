import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from ml.duplicates import best_threshold, haversine_m, pair_table, prepare_meta, prf


def test_haversine_known_distance():
    # 0.01° по широте ≈ 1112 м
    d = haversine_m(np.array([54.0]), np.array([56.0]), np.array([54.01]), np.array([56.0]))[0]
    assert 1100 < d < 1125
    assert haversine_m(np.array([54.0]), np.array([56.0]), np.array([54.0]), np.array([56.0]))[0] == 0


def test_prf():
    y = np.array([True, True, False, False])
    p = np.array([True, False, True, False])
    m = prf(y, p)
    assert (m["tp"], m["fp"], m["fn"]) == (1, 1, 1) and m["f1"] == 0.5


def test_best_threshold_separable():
    score = np.array([0.9, 0.8, 0.2, 0.1])
    y = np.array([True, True, False, False])
    t, f = best_threshold(score, y, np.linspace(0.05, 0.95, 19))
    assert f == 1.0 and 0.2 < t <= 0.8


def toy():
    df = pd.DataFrame({
        "created_at": ["2026-01-01T10:00", "2026-01-02T10:00", "2026-01-02T12:00", "2026-03-01T10:00"],
        "lat": [54.7, 54.7001, 54.8, 54.7], "lon": [56.0, 56.0, 56.1, 56.0],
        "district": ["A", "A", "B", "A"], "problem_id": ["p1", "p1", "p2", "p3"],
    })
    return df


def test_prepare_meta_noise_and_missing():
    df = toy()
    m0 = prepare_meta(df)
    assert m0["has_geo"].all() and np.allclose(m0["lat"], df["lat"])
    big = pd.concat([df] * 500, ignore_index=True)
    m = prepare_meta(big, noise_m=300, missing_frac=0.3, seed=1)
    assert 0.6 < m["has_geo"].mean() < 0.8
    shift_m = np.abs(m["lat"] - big["lat"].to_numpy()) * 111320
    assert 150 < shift_m.std() < 450  # σ ≈ 300 м


def test_missing_geo_flag_in_pairs():
    df = toy()
    meta = prepare_meta(df)
    meta["has_geo"] = np.array([True, False, True, True])
    P = pair_table(np.arange(4), sparse.identity(4, format="csr"), np.eye(4, dtype=np.float32), meta)
    pair01 = (P["a"] == 0) & (P["b"] == 1)
    assert P["geo_missing"][pair01][0] == 1 and P["dist_m"][pair01][0] == 0


def test_pair_table_labels_and_candidates():
    df = toy()
    meta = prepare_meta(df)
    X = sparse.identity(4, format="csr")
    E = np.eye(4, dtype=np.float32)
    idx = np.arange(4)
    full = pair_table(idx, X, E, meta)
    assert len(full["y"]) == 6 and full["y"].sum() == 1  # только пара (0,1) одна проблема
    cand = pair_table(idx, X, E, meta, candidates_only=True)
    assert set(zip(cand["a"], cand["b"])) == {(0, 1)}  # район A и ≤30 суток
    assert cand["y"].all()
