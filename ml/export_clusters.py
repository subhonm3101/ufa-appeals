"""Шаг 5.1 (часть 2а): кластеры дубликатов для всех обращений датасета.

Метод как в Э2: модель на парах + связные компоненты, координаты «clean».
Кластеризуем внутри каждого района (пары из разных районов в модели получают вероятность 0).
Результат: CSV external_id, district, cluster_key. В БД его загрузит отдельный скрипт.

    python ml/export_clusters.py --data data/appeals_synthetic.csv --out data/cluster_assignments.csv
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import adjusted_rand_score

from ml.clustering import cluster_components, full_matrix, tune_threshold
from ml.common import grouped_split, load_dataset
from ml.duplicates import WINDOW_DAYS, lr_features, pair_table, prepare_meta
from ml.embeddings import DEFAULT_MODEL, encode_texts


def prob_matrix(idx, Xtf, E, meta, clf):
    """Симметричная матрица вероятностей «одна проблема» для обращений idx."""
    P = pair_table(idx, Xtf, E, meta)
    cand = P["same_district"] & (P["dt_days"] <= WINDOW_DAYS)
    prob = np.zeros(len(P["y"]), np.float32)
    if cand.any():
        prob[cand] = clf.predict_proba(
            lr_features({k: v[cand] for k, v in P.items()}, True, True))[:, 1]
    return full_matrix(P, prob, len(idx), idx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/appeals_synthetic.csv")
    ap.add_argument("--out", default="data/cluster_assignments.csv")
    ap.add_argument("--cache", default="ml/cache")
    ap.add_argument("--model-name", default=DEFAULT_MODEL)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()

    df = load_dataset(a.data)
    E = encode_texts(df["text"].tolist(), a.model_name, cache_dir=a.cache)
    meta = prepare_meta(df, 0.0, 0.0, a.seed)  # сценарий clean

    # 1) обучаем парную модель и подбираем порог так же, как в Э2
    sp = grouped_split(df, a.seed)
    tr, va, te = sp["train"], sp["val"], sp["test"]
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2).fit(df["text"].iloc[tr])
    Xtf = vec.transform(df["text"])
    P_tr = pair_table(tr, Xtf, E, meta, candidates_only=True)
    clf = LogisticRegression(C=10, class_weight="balanced", max_iter=2000).fit(
        lr_features(P_tr, True, True), P_tr["y"])
    y = df["problem_id"].to_numpy()
    t = tune_threshold(prob_matrix(va, Xtf, E, meta, clf), y[va], "components",
                       np.linspace(0.1, 0.99, 45))
    print(f"Порог (val): {t:.3f}")

    # 2) кластеризуем каждый район отдельно
    district = df["district"].astype(str).to_numpy()
    keys = np.empty(len(df), dtype=object)
    labels_all = np.zeros(len(df), int)
    offset = 0
    for d in sorted(set(district)):
        idx = np.where(district == d)[0]
        lab = cluster_components(prob_matrix(idx, Xtf, E, meta, clf), t)
        labels_all[idx] = lab + offset
        keys[idx] = [f"{d}#{x}" for x in lab]
        offset += lab.max() + 1
        print(f"  {d}: {len(idx)} обращений -> {lab.max() + 1} кластеров")

    out = pd.DataFrame({"external_id": df["external_id"], "district": district, "cluster_key": keys})
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    out.to_csv(a.out, index=False, encoding="utf-8")

    sizes = out.groupby("cluster_key").size()
    print(f"\nВсего кластеров: {len(sizes)} (истинных problem_id: {df['problem_id'].nunique()})")
    print(f"Размер кластера: медиана {sizes.median():.0f}, максимум {sizes.max()}, "
          f"кластеров с 2+ обращениями: {(sizes > 1).sum()}")
    print(f"ARI по test-обращениям (честная оценка): {adjusted_rand_score(y[te], labels_all[te]):.3f}")
    print(f"ARI по всем (завышено, часть обращений была в обучении): "
          f"{adjusted_rand_score(y, labels_all):.3f}")
    print("Сохранено:", a.out)


if __name__ == "__main__":
    main()