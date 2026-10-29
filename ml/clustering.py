"""Э2, часть 2: кластеризация обращений в «проблемы» (шаг 4.4b).

Берём вероятность «дубликат» для каждой пары (модель на парах из duplicates.py) и объединяем обращения в кластеры:
  - components: связные компоненты графа «вероятность ≥ порога» (быстро, но цепочки склеивают лишнее);
  - average:    иерархическая кластеризация со средней связью (осторожнее склеивает).
Порог подбирается на val, качество считается на test: pairwise F1, ARI, число кластеров.

    python ml/clustering.py --data data/appeals_synthetic.csv --seeds 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore", message="Unknown solver options")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial.distance import squareform
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (adjusted_rand_score, completeness_score, homogeneity_score,
                             pair_confusion_matrix)

from ml.common import grouped_split, load_dataset
from ml.duplicates import GEO_SCENARIOS, WINDOW_DAYS, lr_features, pair_table, prepare_meta
from ml.embeddings import DEFAULT_MODEL, encode_texts


def cluster_components(prob: np.ndarray, t: float) -> np.ndarray:
    _, labels = connected_components(csr_matrix(prob >= t), directed=False)
    return labels


def cluster_average(prob: np.ndarray, t: float) -> np.ndarray:
    n = prob.shape[0]
    if n < 2:
        return np.zeros(n, int)
    dist = 1.0 - prob
    np.fill_diagonal(dist, 0.0)
    z = linkage(squareform(dist, checks=False), method="average")
    return fcluster(z, t=1.0 - t, criterion="distance") - 1


METHODS = {"components": cluster_components, "average": cluster_average}


def pair_scores(true_labels, pred_labels) -> dict:
    """Pairwise precision/recall/F1: пара обращений «в одном кластере» против «одна проблема»."""
    (tn, fp), (fn, tp) = pair_confusion_matrix(true_labels, pred_labels)
    tp, fp, fn = tp / 2, fp / 2, fn / 2  # матрица считает упорядоченные пары
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(float(p), 4), "recall": round(float(r), 4), "f1": round(float(f), 4)}


def tune_threshold(prob, true_labels, method, grid):
    best = (float(grid[0]), -1.0)
    for t in grid:
        f = pair_scores(true_labels, METHODS[method](prob, t))["f1"]
        if f > best[1]:
            best = (float(t), f)
    return best[0]


def full_matrix(P: dict, values: np.ndarray, n: int, idx: np.ndarray) -> np.ndarray:
    """Из списка пар i<j делает симметричную матрицу n x n (по позициям внутри idx)."""
    pos = {g: i for i, g in enumerate(idx)}
    ia = np.fromiter((pos[g] for g in P["a"]), int, len(P["a"]))
    ib = np.fromiter((pos[g] for g in P["b"]), int, len(P["b"]))
    M = np.zeros((n, n), np.float32)
    M[ia, ib] = values
    M[ib, ia] = values
    np.fill_diagonal(M, 1.0)
    return M


def evaluate_seed(df, E, meta, seed):
    sp = grouped_split(df, seed)
    tr, va, te = sp["train"], sp["val"], sp["test"]
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2).fit(df["text"].iloc[tr])
    Xtf = vec.transform(df["text"])
    P_tr = pair_table(tr, Xtf, E, meta, candidates_only=True)
    clf = LogisticRegression(C=10, class_weight="balanced", max_iter=2000).fit(
        lr_features(P_tr, True, True), P_tr["y"])

    def matrices(idx):
        P = pair_table(idx, Xtf, E, meta)
        cand = P["same_district"] & (P["dt_days"] <= WINDOW_DAYS)
        prob = np.zeros(len(P["y"]), np.float32)
        prob[cand] = clf.predict_proba(lr_features({k: v[cand] for k, v in P.items()}, True, True))[:, 1]
        return {"model": full_matrix(P, prob, len(idx), idx), "tfidf": full_matrix(P, P["tf"], len(idx), idx)}

    M_va, M_te = matrices(va), matrices(te)
    y_va, y_te = df["problem_id"].to_numpy()[va], df["problem_id"].to_numpy()[te]
    grid = np.linspace(0.1, 0.99, 45)
    res = {"seed": seed, "n_test": int(len(te)), "true_clusters": int(len(set(y_te))), "runs": {}}
    for src in ("tfidf", "model"):
        for method in METHODS:
            t = tune_threshold(M_va[src], y_va, method, grid)
            pred = METHODS[method](M_te[src], t)
            r = pair_scores(y_te, pred)
            r.update(threshold=round(t, 3), ari=round(float(adjusted_rand_score(y_te, pred)), 4),
                     homogeneity=round(float(homogeneity_score(y_te, pred)), 4),
                     completeness=round(float(completeness_score(y_te, pred)), 4),
                     clusters=int(len(set(pred))))
            res["runs"][f"{src}+{method}"] = r
    return res


def summarize(per_seed):
    out = {}
    for k in per_seed[0]["runs"]:
        out[k] = {}
        for m in ("precision", "recall", "f1", "ari", "clusters"):
            v = np.array([r["runs"][k][m] for r in per_seed], float)
            out[k][m] = {"mean": round(float(v.mean()), 4), "std": round(float(v.std(ddof=1)) if len(v) > 1 else 0.0, 4)}
    return out


NAMES = {"tfidf+components": "Текст (TF-IDF), связные компоненты", "tfidf+average": "Текст (TF-IDF), средняя связь",
         "model+components": "Модель на парах, связные компоненты", "model+average": "Модель на парах, средняя связь"}


def table_md(summ, true_clusters):
    lines = [f"| Метод | Pairwise F1 | ARI | Кластеров (истинно ≈ {true_clusters}) |", "|---|---|---|---|"]
    for k, v in summ.items():
        lines.append(f"| {NAMES[k]} | {v['f1']['mean']:.3f} ± {v['f1']['std']:.3f} | "
                     f"{v['ari']['mean']:.3f} ± {v['ari']['std']:.3f} | {v['clusters']['mean']:.0f} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/appeals_synthetic.csv")
    ap.add_argument("--out", default="ml/results")
    ap.add_argument("--cache", default="ml/cache")
    ap.add_argument("--model-name", default=DEFAULT_MODEL)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--base-seed", type=int, default=2026)
    ap.add_argument("--scenarios", default="clean,noisy")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    df = load_dataset(a.data)
    E = encode_texts(df["text"].tolist(), a.model_name, cache_dir=a.cache)
    result, md = {"model": a.model_name, "scenarios": {}}, []
    for sc in a.scenarios.split(","):
        noise, miss = GEO_SCENARIOS[sc]
        per_seed = []
        for s in range(a.base_seed, a.base_seed + a.seeds):
            r = evaluate_seed(df, E, prepare_meta(df, noise, miss, s), s)
            per_seed.append(r)
            print(f"[{sc}] seed={s}: " + " | ".join(f"{k}: F1={v['f1']:.3f}" for k, v in r["runs"].items()))
        summ = summarize(per_seed)
        tc = int(np.mean([r["true_clusters"] for r in per_seed]))
        result["scenarios"][sc] = {"geo_noise_m": noise, "geo_missing_frac": miss, "per_seed": per_seed, "summary": summ}
        md.append(f"**Координаты: {sc} (шум {noise} м, без координат {int(miss * 100)}%)**\n\n" + table_md(summ, tc))
        print(f"\n[{sc}]\n" + table_md(summ, tc) + "\n")
    with open(os.path.join(a.out, "e2_clustering.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "e2_clustering_table.md"), "w", encoding="utf-8") as f:
        f.write("\n\n".join(md) + "\n")
    print("Сохранено:", os.path.join(a.out, "e2_clustering.json"), "и e2_clustering_table.md")


if __name__ == "__main__":
    main()
