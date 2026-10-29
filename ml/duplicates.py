"""Э2, часть 1: поиск дубликатов обращений (шаг 4.4a).

Дубликат: два обращения об одной проблеме (одинаковый problem_id). Сравниваем способы:
  1) только текст, TF-IDF косинус;   2) только текст, rubert-tiny2 косинус;
  3) только место и время (без текста);   4) комбинация признаков (логистическая регрессия на парах).
Пары берутся внутри одной выборки (train/val/test делятся по problem_id, как в 4.1),
порог подбирается на val, итог считается на test.

    python ml/duplicates.py --data data/appeals_synthetic.csv --seeds 3
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
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

from ml.common import grouped_split, load_dataset
from ml.embeddings import DEFAULT_MODEL, encode_texts

WINDOW_DAYS = 30.0  # кандидаты для комбинированной модели: тот же район и не дальше 30 суток


def haversine_m(lat1, lon1, lat2, lon2):
    """Расстояние в метрах между точками (массивы numpy, градусы)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dl = p2 - p1, np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * 6371000 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


GEO_SCENARIOS = {  # название: (шум координат в метрах, доля обращений без координат)
    "clean": (0, 0.0),
    "noisy": (300, 0.3),
    "harsh": (1000, 0.5),
}


def prepare_meta(df: pd.DataFrame, noise_m: float = 0.0, missing_frac: float = 0.0, seed: int = 0) -> dict:
    """Метаданные обращений. noise_m и missing_frac портят координаты, как это бывает в реальных данных."""
    t = pd.to_datetime(df["created_at"], utc=True, format="ISO8601")
    lat, lon = df["lat"].to_numpy(float).copy(), df["lon"].to_numpy(float).copy()
    rng = np.random.default_rng(seed + 17)
    if noise_m > 0:
        lat += rng.normal(0, noise_m / 111320, len(lat))
        lon += rng.normal(0, noise_m / (111320 * np.cos(np.radians(lat))), len(lon))
    has_geo = rng.random(len(lat)) >= missing_frac if missing_frac > 0 else np.ones(len(lat), bool)
    return {
        "days": ((t - t.min()).dt.total_seconds() / 86400).to_numpy(),
        "lat": lat, "lon": lon, "has_geo": has_geo,
        "district": df["district"].astype(str).to_numpy(), "problem": df["problem_id"].to_numpy(),
    }


def pair_table(idx, Xtf, E, meta, candidates_only=False) -> dict[str, np.ndarray]:
    """Все пары i<j внутри idx с признаками и меткой «одна проблема»."""
    n = len(idx)
    iu, ju = np.triu_indices(n, 1)
    a, b = idx[iu], idx[ju]
    tf = (Xtf[idx] @ Xtf[idx].T).toarray().astype(np.float32)[iu, ju]
    em = (E[idx] @ E[idx].T).astype(np.float32)[iu, ju]
    dist = haversine_m(meta["lat"][a], meta["lon"][a], meta["lat"][b], meta["lon"][b]).astype(np.float32)
    geo_missing = ~(meta["has_geo"][a] & meta["has_geo"][b])
    dist = np.where(geo_missing, 0, dist).astype(np.float32)  # расстояние неизвестно: ставим 0 и флаг
    dt = np.abs(meta["days"][a] - meta["days"][b]).astype(np.float32)
    same_d = meta["district"][a] == meta["district"][b]
    y = (meta["problem"][a] == meta["problem"][b])
    out = {"tf": tf, "em": em, "dist_m": dist, "dt_days": dt, "same_district": same_d, "y": y,
           "geo_missing": geo_missing.astype(np.float32), "a": a, "b": b}
    if candidates_only:
        keep = same_d & (dt <= WINDOW_DAYS)
        out = {k: v[keep] for k, v in out.items()}
    return out


def prf(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    tp = int((y_true & y_pred).sum())
    fp = int((~y_true & y_pred).sum())
    fn = int((y_true & ~y_pred).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4), "tp": tp, "fp": fp, "fn": fn}


def best_threshold(score: np.ndarray, y: np.ndarray, grid: np.ndarray) -> tuple[float, float]:
    """Порог, при котором F1 на val максимален: (порог, F1)."""
    best = (float(grid[0]), -1.0)
    for t in grid:
        f = prf(y, score >= t)["f1"]
        if f > best[1]:
            best = (float(t), f)
    return best


def geo_rule_grid(val, test_pairs=None):
    best = None
    for d in (25, 50, 100, 200, 500, 1000):
        for w in (1, 2, 3, 5, 7, 10, 14):
            pred = (val["dist_m"] <= d) & (val["dt_days"] <= w) & (val["geo_missing"] == 0)
            f = prf(val["y"], pred)["f1"]
            if best is None or f > best[0]:
                best = (f, d, w)
    return best[1], best[2]


def lr_features(p: dict, use_text: bool, use_geo: bool) -> np.ndarray:
    cols = []
    if use_text:
        cols += [p["tf"], p["em"]]
    if use_geo:
        cols += [np.log1p(p["dist_m"]), np.log1p(p["dt_days"]), p["geo_missing"]]
    return np.column_stack(cols).astype(np.float32)


def evaluate_seed(df, E, meta, seed):
    sp = grouped_split(df, seed)
    tr, va, te = sp["train"], sp["val"], sp["test"]
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2).fit(df["text"].iloc[tr])
    Xtf = vec.transform(df["text"])

    P_tr = pair_table(tr, Xtf, E, meta, candidates_only=True)
    P_va = pair_table(va, Xtf, E, meta)
    P_te = pair_table(te, Xtf, E, meta)
    y_va, y_te = P_va["y"], P_te["y"]
    grid = np.linspace(0.2, 0.995, 160)
    res = {"seed": seed, "pairs_test": int(len(y_te)), "positive_pairs_test": int(y_te.sum()), "methods": {}}

    for name, key in (("text_tfidf", "tf"), ("text_rubert", "em")):
        t, _ = best_threshold(P_va[key], y_va, grid)
        m = prf(y_te, P_te[key] >= t)
        m.update(threshold=round(t, 3), ap=round(float(average_precision_score(y_te, P_te[key])), 4))
        res["methods"][name] = m

    d, w = geo_rule_grid(P_va)
    m = prf(y_te, (P_te["dist_m"] <= d) & (P_te["dt_days"] <= w) & (P_te["geo_missing"] == 0))
    m.update(rule=f"расстояние ≤ {d} м и разница ≤ {w} сут.")
    res["methods"]["place_time_only"] = m

    cand_te = P_te["same_district"] & (P_te["dt_days"] <= WINDOW_DAYS)
    cand_va = P_va["same_district"] & (P_va["dt_days"] <= WINDOW_DAYS)
    for name, (use_t, use_g) in (("combined_text_only", (True, False)), ("combined_place_time_only", (False, True)),
                                 ("combined_all", (True, True))):
        clf = LogisticRegression(C=10, class_weight="balanced", max_iter=2000)
        clf.fit(lr_features(P_tr, use_t, use_g), P_tr["y"])
        prob_va = np.zeros(len(y_va), np.float32)
        prob_va[cand_va] = clf.predict_proba(lr_features({k: v[cand_va] for k, v in P_va.items()}, use_t, use_g))[:, 1]
        t, _ = best_threshold(prob_va, y_va, np.linspace(0.05, 0.99, 95))
        prob_te = np.zeros(len(y_te), np.float32)
        prob_te[cand_te] = clf.predict_proba(lr_features({k: v[cand_te] for k, v in P_te.items()}, use_t, use_g))[:, 1]
        m = prf(y_te, prob_te >= t)
        m.update(threshold=round(t, 3), ap=round(float(average_precision_score(y_te, prob_te)), 4))
        res["methods"][name] = m

    # почему одного текста мало: доля ложных срабатываний TF-IDF среди пар с тем же районом
    t = res["methods"]["text_tfidf"]["threshold"]
    fp = (P_te["tf"] >= t) & ~y_te
    res["tfidf_false_positives"] = {
        "count": int(fp.sum()),
        "share_same_district": round(float(P_te["same_district"][fp].mean()), 3) if fp.any() else None,
        "median_dist_m": round(float(np.median(P_te["dist_m"][fp])), 0) if fp.any() else None,
        "median_dt_days": round(float(np.median(P_te["dt_days"][fp])), 1) if fp.any() else None,
    }
    return res


def summarize(per_seed: list[dict]) -> dict:
    out = {}
    for m in per_seed[0]["methods"]:
        out[m] = {}
        for k in ("precision", "recall", "f1"):
            v = np.array([r["methods"][m][k] for r in per_seed])
            out[m][k] = {"mean": round(float(v.mean()), 4),
                         "std": round(float(v.std(ddof=1)) if len(v) > 1 else 0.0, 4)}
    return out


NAMES = {"text_tfidf": "Только текст, TF-IDF", "text_rubert": "Только текст, rubert-tiny2",
         "place_time_only": "Только место и время", "combined_text_only": "Модель на парах: только текст",
         "combined_place_time_only": "Модель на парах: только место и время",
         "combined_all": "Модель на парах: текст + место + время"}


def table_md(summ: dict) -> str:
    lines = ["| Метод | Precision | Recall | F1 |", "|---|---|---|---|"]
    for k, v in summ.items():
        lines.append(f"| {NAMES[k]} | {v['precision']['mean']:.3f} ± {v['precision']['std']:.3f} "
                     f"| {v['recall']['mean']:.3f} ± {v['recall']['std']:.3f} "
                     f"| {v['f1']['mean']:.3f} ± {v['f1']['std']:.3f} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/appeals_synthetic.csv")
    ap.add_argument("--out", default="ml/results")
    ap.add_argument("--cache", default="ml/cache")
    ap.add_argument("--model-name", default=DEFAULT_MODEL)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--base-seed", type=int, default=2026)
    ap.add_argument("--scenarios", default="clean,noisy,harsh", help="из: " + ", ".join(GEO_SCENARIOS))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    df = load_dataset(a.data)
    for c in ("created_at", "lat", "lon", "district"):
        if c not in df.columns:
            raise SystemExit(f"Нужна колонка {c}")
    E = encode_texts(df["text"].tolist(), a.model_name, cache_dir=a.cache)

    result, md = {"model": a.model_name, "scenarios": {}}, []
    for sc in a.scenarios.split(","):
        noise, miss = GEO_SCENARIOS[sc]
        per_seed = []
        for s in range(a.base_seed, a.base_seed + a.seeds):
            r = evaluate_seed(df, E, prepare_meta(df, noise, miss, s), s)
            per_seed.append(r)
            print(f"[{sc}] seed={s}: " + " | ".join(f"{k}: F1={v['f1']:.3f}" for k, v in r["methods"].items()))
        summ = summarize(per_seed)
        result["scenarios"][sc] = {"geo_noise_m": noise, "geo_missing_frac": miss,
                                   "per_seed": per_seed, "summary": summ}
        md.append(f"**Координаты: {sc} (шум {noise} м, без координат {int(miss * 100)}%)**\n\n" + table_md(summ))
        print(f"\n[{sc}] шум {noise} м, без координат {int(miss * 100)}%\n" + table_md(summ) + "\n")
    with open(os.path.join(a.out, "e2_duplicates.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "e2_duplicates_table.md"), "w", encoding="utf-8") as f:
        f.write("\n\n".join(md) + "\n")
    print("Сохранено:", os.path.join(a.out, "e2_duplicates.json"), "и e2_duplicates_table.md")


if __name__ == "__main__":
    main()
