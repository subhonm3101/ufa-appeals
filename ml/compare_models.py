"""Э1, итог: сравнение TF-IDF и rubert-tiny2 на нескольких разбиениях (шаг 4.3a).

Для каждого seed деление выборок и (в сценарии B) набор «невиданных» подтем меняются.
Так видно, не случайна ли разница между моделями.

    python ml/compare_models.py --data data/appeals_synthetic.csv --seeds 5
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import warnings

warnings.filterwarnings("ignore", message="Unknown solver options")  # безвредное предупреждение scipy
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score

from ml.common import load_dataset
from ml.embeddings import DEFAULT_MODEL, encode_texts
from ml.train_tfidf_baseline import C_GRID, SCENARIOS, build_model

MODELS = ("tfidf", "rubert")


def summarize(per_seed: list[dict]) -> dict:
    """per_seed: [{'tfidf': {'macro_f1':..,'accuracy':..}, 'rubert': {...}}, ...] -> средние, разброс, парная разница."""
    out = {}
    for m in MODELS:
        out[m] = {}
        for metric in ("macro_f1", "accuracy"):
            v = np.array([r[m][metric] for r in per_seed], dtype=float)
            out[m][metric] = {"mean": round(float(v.mean()), 4),
                              "std": round(float(v.std(ddof=1)) if len(v) > 1 else 0.0, 4)}
    d = np.array([r["rubert"]["macro_f1"] - r["tfidf"]["macro_f1"] for r in per_seed], dtype=float)
    out["diff_macro_f1_rubert_minus_tfidf"] = {
        "mean": round(float(d.mean()), 4),
        "std": round(float(d.std(ddof=1)) if len(d) > 1 else 0.0, 4),
        "min": round(float(d.min()), 4), "max": round(float(d.max()), 4),
        "rubert_wins": int((d > 0).sum()), "seeds": int(len(d)),
    }
    return out


def markdown_table(summary: dict) -> str:
    lines = ["| Сценарий | TF-IDF macro-F1 | rubert-tiny2 macro-F1 | Разница (rubert − TF-IDF) | rubert лучше |",
             "|---|---|---|---|---|"]
    for key, (title, _) in SCENARIOS.items():
        s = summary[key]
        d = s["diff_macro_f1_rubert_minus_tfidf"]
        lines.append(
            f"| {title} | {s['tfidf']['macro_f1']['mean']:.3f} ± {s['tfidf']['macro_f1']['std']:.3f} "
            f"| {s['rubert']['macro_f1']['mean']:.3f} ± {s['rubert']['macro_f1']['std']:.3f} "
            f"| {d['mean']:+.3f} ± {d['std']:.3f} | {d['rubert_wins']} из {d['seeds']} |")
    return "\n".join(lines)


def _fit_eval(make, Xtr, ytr, Xva, yva, Xte, yte):
    best = None
    for c in C_GRID:
        m = make(c).fit(Xtr, ytr)
        f1 = f1_score(yva, m.predict(Xva), average="macro")
        if best is None or f1 > best[0]:
            best = (f1, c)
    m = make(best[1]).fit(Xtr, ytr)
    p = m.predict(Xte)
    return {"macro_f1": float(f1_score(yte, p, average="macro")),
            "accuracy": float(accuracy_score(yte, p)), "C": best[1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/appeals_synthetic.csv")
    ap.add_argument("--out", default="ml/results")
    ap.add_argument("--cache", default="ml/cache")
    ap.add_argument("--model-name", default=DEFAULT_MODEL)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--base-seed", type=int, default=2026)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    df = load_dataset(a.data)
    texts, y = df["text"].values, df["category"].values
    X = encode_texts(df["text"].tolist(), a.model_name, cache_dir=a.cache)
    seeds = [a.base_seed + i for i in range(a.seeds)]

    raw: dict[str, list[dict]] = {k: [] for k in SCENARIOS}
    for key, (title, fn) in SCENARIOS.items():
        for s in seeds:
            sp = fn(df, s)
            tr, va, te = sp["train"], sp["val"], sp["test"]
            r_tf = _fit_eval(build_model, texts[tr], y[tr], texts[va], y[va], texts[te], y[te])
            r_rb = _fit_eval(lambda c: LogisticRegression(C=c, class_weight="balanced", max_iter=3000),
                             X[tr], y[tr], X[va], y[va], X[te], y[te])
            raw[key].append({"seed": s, "tfidf": r_tf, "rubert": r_rb})
            print(f"{key} seed={s}: TF-IDF {r_tf['macro_f1']:.3f} | rubert {r_rb['macro_f1']:.3f}")
    summary = {k: summarize(v) for k, v in raw.items()}
    table = markdown_table(summary)
    res = {"seeds": seeds, "n": len(df), "model": a.model_name,
           "versions": {"python": platform.python_version(), "scikit-learn": sklearn.__version__,
                        "numpy": np.__version__},
           "per_seed": raw, "summary": summary}
    with open(os.path.join(a.out, "e1_multiseed.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "e1_table.md"), "w", encoding="utf-8") as f:
        f.write(table + "\n")
    print("\n" + table)
    print("\nСохранено:", os.path.join(a.out, "e1_multiseed.json"), "и e1_table.md")


if __name__ == "__main__":
    main()
