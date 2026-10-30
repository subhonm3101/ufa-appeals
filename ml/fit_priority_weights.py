"""Шаг 5.3: подбор весов приоритета по экспертной разметке и проверка моделей (эксперимент Э3, часть 2).

    python ml/fit_priority_weights.py

Сравниваем способы ранжировать кластеры (метрики на отложенных данных, деление по подтемам):
  rules_v1   формула с весами, заданными вручную (без обучения)
  equal      все пять компонентов с равными весами
  weights    веса компонентов, подобранные по разметке (неотрицательная регрессия, NNLS)
  text       только текст кластера (эмбеддинги rubert-tiny2 + ridge)
  hybrid     подобранные веса + текстовая поправка

Читает:  data/labeling/{expert_labels,priority_table,cluster_members}.csv, data/appeals_synthetic.csv, ml/cache
Пишет:   data/priority_weights_v2.json (для run_priority.py), ml/results/e3_models.json, e3_models_table.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import pandas as pd
from scipy.optimize import nnls
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ml.e3_metrics import ndcg, rand_ndcg, safe_rho

COMP = ["urgency", "significance", "scale", "age", "dynamics"]
RULES_W = {"urgency": 0.35, "significance": 0.20, "scale": 0.25, "age": 0.10, "dynamics": 0.10}
NAMES = {"rules_v1": "Формула rules_v1 (веса вручную)", "equal": "Равные веса",
         "weights": "Подобранные веса (NNLS)", "text": "Только текст (rubert-tiny2 + ridge)",
         "hybrid": "Подобранные веса + текст", "random": "Случайный порядок"}


def nnls_fit(X, y):
    xm, ym = X.mean(0), y.mean()
    w, _ = nnls(X - xm, y - ym)
    if w.sum() <= 1e-12:
        w = np.ones(X.shape[1])
    return w, xm, ym


def nnls_pred(X, fit):
    w, xm, ym = fit
    return (X - xm) @ w + ym


def ridge():
    return make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-1, 3, 15)))


def fit_predict(name, Xc_tr, Xe_tr, y_tr, Xc_te, Xe_te):
    if name == "weights":
        return nnls_pred(Xc_te, nnls_fit(Xc_tr, y_tr))
    if name == "text":
        return ridge().fit(Xe_tr, y_tr).predict(Xe_te)
    if name == "hybrid":
        fit = nnls_fit(Xc_tr, y_tr)
        res = y_tr - nnls_pred(Xc_tr, fit)
        return nnls_pred(Xc_te, fit) + ridge().fit(Xe_tr, res).predict(Xe_te)
    raise ValueError(name)


def group_folds(groups, k, rng):
    u = np.unique(groups)
    rng.shuffle(u)
    of = {g: i % k for i, g in enumerate(u)}
    return np.array([of[g] for g in groups])


def metrics(y, s, rng=None):
    return {"spearman": safe_rho(s, y), "ndcg10": ndcg(y, s, 10), "ndcg20": ndcg(y, s, 20)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/labeling")
    ap.add_argument("--data", default="data/appeals_synthetic.csv")
    ap.add_argument("--cache", default="ml/cache")
    ap.add_argument("--model-name", default=None)
    ap.add_argument("--out", default="ml/results")
    ap.add_argument("--weights-out", default="data/priority_weights_v2.json")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)

    lab = pd.read_csv(os.path.join(a.dir, "expert_labels.csv"))
    tab = pd.read_csv(os.path.join(a.dir, "priority_table.csv"), encoding="utf-8-sig").rename(columns={"score": "score_rules"})
    mem = pd.read_csv(os.path.join(a.dir, "cluster_members.csv"))
    df = lab.merge(tab[["cluster_id", "score_rules"] + COMP], on="cluster_id", how="inner").reset_index(drop=True)
    if len(df) < 30:
        sys.exit(f"После объединения осталось {len(df)} кластеров, этого мало")

    # текст кластера: среднее эмбеддингов его обращений; группа для деления = основная подтема
    from ml.common import load_dataset
    from ml.embeddings import DEFAULT_MODEL, encode_texts
    data = load_dataset(a.data)
    E = encode_texts(data["text"].tolist(), a.model_name or DEFAULT_MODEL, cache_dir=a.cache)
    pos = {e: i for i, e in enumerate(data["external_id"])}
    sub = data["subtopic"].fillna("none").to_numpy()
    emb, grp = [], []
    for cid in df["cluster_id"]:
        idx = [pos[e] for e in mem.loc[mem["cluster_id"] == cid, "external_id"] if e in pos]
        if not idx:
            sys.exit(f"Для кластера {cid} нет обращений в датасете, проверь cluster_members.csv")
        v = E[idx].mean(0)
        emb.append(v / (np.linalg.norm(v) + 1e-9))
        vals, cnt = np.unique(sub[idx], return_counts=True)
        grp.append(vals[cnt.argmax()])
    Xe, grp = np.vstack(emb), np.array(grp)
    Xc, y = df[COMP].to_numpy(float), df["rating"].to_numpy(float)
    n = len(df)
    print(f"Кластеров с оценками: {n}, подтем (групп для честного деления): {len(np.unique(grp))}")

    # 1) модели без обучения
    base = {"rules_v1": df["score_rules"].to_numpy(float), "equal": Xc.mean(1)}
    results, oof_mean = {}, {}
    for k, s in base.items():
        m = metrics(y, s)
        results[k] = {x: {"mean": round(v, 3), "std": 0.0} for x, v in m.items()}
        oof_mean[k] = pd.Series(s).rank().to_numpy()

    # 2) модели с обучением: многократная кросс-валидация, подтемы не пересекаются между обучением и проверкой
    per = {k: [] for k in ("weights", "text", "hybrid")}
    ranks = {k: np.zeros(n) for k in per}
    for r in range(a.repeats):
        fold = group_folds(grp, a.folds, rng)
        for name in per:
            oof = np.zeros(n)
            for f in range(a.folds):
                tr, te = fold != f, fold == f
                oof[te] = fit_predict(name, Xc[tr], Xe[tr], y[tr], Xc[te], Xe[te])
            per[name].append(metrics(y, oof))
            ranks[name] += pd.Series(oof).rank().to_numpy()
    for k, lst in per.items():
        results[k] = {x: {"mean": round(float(np.mean([m[x] for m in lst])), 3),
                          "std": round(float(np.std([m[x] for m in lst], ddof=1)), 3)} for x in lst[0]}
        oof_mean[k] = ranks[k] / a.repeats
    results["random"] = {"spearman": {"mean": 0.0, "std": 0.0},
                         "ndcg10": {"mean": round(rand_ndcg(y, 10, rng), 3), "std": 0.0},
                         "ndcg20": {"mean": round(rand_ndcg(y, 20, rng), 3), "std": 0.0}}

    lines = ["| Способ | Спирмен | NDCG@10 | NDCG@20 |", "|---|---|---|---|"]
    for k in ("rules_v1", "equal", "weights", "text", "hybrid", "random"):
        v = results[k]
        lines.append(f"| {NAMES[k]} | {v['spearman']['mean']:.3f} ± {v['spearman']['std']:.3f} | "
                     f"{v['ndcg10']['mean']:.3f} ± {v['ndcg10']['std']:.3f} | {v['ndcg20']['mean']:.3f} ± {v['ndcg20']['std']:.3f} |")
    table = "\n".join(lines)
    print("\n=== Качество ранжирования на отложенных подтемах (±: разброс по повторам деления) ===\n" + table)

    # 3) значимость различий с rules_v1: бутстреп по кластерам
    idx_b = rng.integers(0, n, (a.boot, n))
    diffs = {}
    for k in ("equal", "weights", "text", "hybrid"):
        d = np.array([safe_rho(oof_mean[k][i], y[i]) - safe_rho(oof_mean["rules_v1"][i], y[i]) for i in idx_b])
        lo, hi = np.nanpercentile(d, [2.5, 97.5])
        diffs[k] = {"delta_spearman": round(safe_rho(oof_mean[k], y) - safe_rho(oof_mean["rules_v1"], y), 3),
                    "ci95": [round(float(lo), 3), round(float(hi), 3)]}
    print("\nРазница по Спирмену относительно rules_v1 (95% ДИ бутстрепом; если ДИ включает 0, преимущество не доказано):")
    for k, v in diffs.items():
        sign = "значимо" if (v["ci95"][0] > 0 or v["ci95"][1] < 0) else "в пределах шума"
        print(f"  {NAMES[k]}: {v['delta_spearman']:+.3f}  [{v['ci95'][0]:+.3f}; {v['ci95'][1]:+.3f}]  {sign}")

    # 4) итоговые веса и их устойчивость
    w, _, _ = nnls_fit(Xc, y)
    wn = w / w.sum()
    boot_w = []
    for i in rng.integers(0, n, (300, n)):
        bw, _, _ = nnls_fit(Xc[i], y[i])
        boot_w.append(bw / bw.sum())
    boot_w = np.array(boot_w)
    print("\nПодобранные веса (на всех кластерах) и их устойчивость по 300 бутстреп-выборкам:")
    print("  компонент       вручную  подобрано  бутстреп (среднее ± ст.откл.)  доля выборок с весом > 0.02")
    for j, c in enumerate(COMP):
        print(f"  {c:<14} {RULES_W[c]:7.2f} {wn[j]:10.3f}   {boot_w[:, j].mean():.3f} ± {boot_w[:, j].std():.3f}"
              f"                  {(boot_w[:, j] > 0.02).mean():.0%}")
    weights = {c: round(float(wn[j]), 4) for j, c in enumerate(COMP)}
    weights[COMP[int(np.argmax(wn))]] = round(1.0 - sum(v for c, v in weights.items() if c != COMP[int(np.argmax(wn))]), 4)
    os.makedirs(os.path.dirname(a.weights_out) or ".", exist_ok=True)
    with open(a.weights_out, "w", encoding="utf-8") as f:
        json.dump({"method": "rules_v2", "weights": weights, "fitted_on_clusters": int(n),
                   "note": "NNLS по экспертной разметке (итоговая оценка двух раундов), нормировано на сумму 1"},
                  f, ensure_ascii=False, indent=2)

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "e3_models.json"), "w", encoding="utf-8") as f:
        json.dump({"n_clusters": int(n), "n_groups": int(len(np.unique(grp))), "folds": a.folds, "repeats": a.repeats,
                   "results": results, "delta_vs_rules_v1": diffs, "weights": weights,
                   "weights_bootstrap_mean": {c: round(float(boot_w[:, j].mean()), 4) for j, c in enumerate(COMP)},
                   "weights_bootstrap_std": {c: round(float(boot_w[:, j].std()), 4) for j, c in enumerate(COMP)}},
                  f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "e3_models_table.md"), "w", encoding="utf-8") as f:
        f.write(table + "\n")
    print(f"\nСохранено: {a.weights_out}, {a.out}/e3_models.json, e3_models_table.md")


if __name__ == "__main__":
    main()
