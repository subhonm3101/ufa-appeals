"""Э1, часть 1: базовый классификатор категорий (TF-IDF + логистическая регрессия), шаг 4.1.

Запуск из корня проекта:
    python ml/train_tfidf_baseline.py --data data/appeals_synthetic.csv --out ml/results --models ml/models
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
import time

warnings.filterwarnings("ignore", message="Unknown solver options")  # безвредное предупреждение scipy
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import FeatureUnion, Pipeline

from ml.common import (assert_no_group_leak, grouped_split, heldout_subtopic_split,
                       load_dataset, random_split, split_summary)

C_GRID = [0.3, 1, 3, 10, 30, 100, 300]
SCENARIOS = {
    "A_grouped": ("A. Деление по problem_id", grouped_split),
    "B_heldout_subtopics": ("B. Тест из невиданных подтем", heldout_subtopic_split),
    "C_random_leak": ("C. Случайное деление (утечка)", random_split),
}


def build_model(c: float) -> Pipeline:
    feats = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2, lowercase=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2)),
    ])
    clf = LogisticRegression(C=c, class_weight="balanced", max_iter=3000)
    return Pipeline([("tfidf", feats), ("clf", clf)])


def top_terms(model: Pipeline, k: int = 8) -> dict[str, list[str]]:
    names = np.array(model.named_steps["tfidf"].get_feature_names_out())
    clf = model.named_steps["clf"]
    out = {}
    for i, cls in enumerate(clf.classes_):
        idx = np.argsort(clf.coef_[i])[::-1]
        out[cls] = [n.split("__", 1)[-1] for n in names[idx] if n.startswith("word__")][:k]
    return out


def plot_cm(cm, labels, title, path):
    cmn = cm / cm.sum(axis=1, keepdims=True)
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    im = ax.imshow(cmn, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, f"{cmn[i, j]:.2f}", ha="center", va="center",
                    color="white" if cmn[i, j] > 0.5 else "black", fontsize=8)
    ax.set_xlabel("Предсказано")
    ax.set_ylabel("Эксперт (истина)")
    ax.set_title(title, fontsize=10)
    fig.colorbar(im, fraction=0.046)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run_scenario(key, title, fn, df, out_dir, models_dir, seed):
    split = fn(df, seed)
    leak = False
    try:
        assert_no_group_leak(df, split)
    except AssertionError:
        leak = True
    tr, va, te = (df.iloc[split[s]] for s in ("train", "val", "test"))
    ytr, yva, yte = tr["category"], va["category"], te["category"]

    dummy = DummyClassifier(strategy="most_frequent").fit(tr["text"], ytr)
    dpred = dummy.predict(te["text"])

    best = None
    grid = {}
    for c in C_GRID:
        m = build_model(c).fit(tr["text"], ytr)
        f1 = f1_score(yva, m.predict(va["text"]), average="macro")
        grid[str(c)] = round(f1, 4)
        if best is None or f1 > best[0]:
            best = (f1, c)
    best_c = best[1]

    t0 = time.perf_counter()
    model = build_model(best_c).fit(tr["text"], ytr)
    train_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    pred = model.predict(te["text"])
    latency_ms = (time.perf_counter() - t0) / len(te) * 1000

    labels = sorted(df["category"].unique())
    cm = confusion_matrix(yte, pred, labels=labels)
    rep = classification_report(yte, pred, labels=labels, output_dict=True, zero_division=0)
    ok = (pred == yte.values)
    per_sub = (te.assign(ok=ok).groupby(["category", "subtopic"])["ok"].agg(["mean", "size"])
               .rename(columns={"mean": "accuracy", "size": "n"}).round(3).reset_index())
    worst = per_sub.sort_values("accuracy").head(8).to_dict("records")

    res = {
        "scenario": title, "group_leak_between_train_test": leak,
        "split": split_summary(df, split).to_dict("records"),
        "best_C": best_c, "val_macro_f1_by_C": grid,
        "test": {"accuracy": round(accuracy_score(yte, pred), 4),
                 "macro_f1": round(f1_score(yte, pred, average="macro"), 4),
                 "weighted_f1": round(f1_score(yte, pred, average="weighted"), 4)},
        "dummy_majority": {"accuracy": round(accuracy_score(yte, dpred), 4),
                           "macro_f1": round(f1_score(yte, dpred, average="macro", zero_division=0), 4)},
        "per_class": {k: {m: round(v, 4) for m, v in rep[k].items()} for k in labels},
        "confusion_matrix": {"labels": labels, "matrix": cm.tolist()},
        "worst_subtopics": worst,
        "top_terms": top_terms(model),
        "train_seconds": round(train_s, 2), "predict_ms_per_text": round(latency_ms, 4),
    }
    plot_cm(cm, labels, f"{title}\nmacro-F1 = {res['test']['macro_f1']}", os.path.join(out_dir, f"cm_{key}.png"))
    joblib.dump(model, os.path.join(models_dir, f"tfidf_logreg_{key}.joblib"))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/appeals_synthetic.csv")
    ap.add_argument("--out", default="ml/results")
    ap.add_argument("--models", default="ml/models")
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.models, exist_ok=True)

    df = load_dataset(a.data)
    print(f"Данные: {len(df)} обращений, {df['problem_id'].nunique()} проблем, {df['category'].nunique()} категорий\n")
    results = {}
    for key, (title, fn) in SCENARIOS.items():
        r = run_scenario(key, title, fn, df, a.out, a.models, a.seed)
        results[key] = r
        print(f"{title}\n  утечка problem_id train/test: {'ДА' if r['group_leak_between_train_test'] else 'нет'}; "
              f"C={r['best_C']}\n  TF-IDF+LogReg: accuracy={r['test']['accuracy']}, macro-F1={r['test']['macro_f1']}\n"
              f"  Базовая (всегда главный класс): accuracy={r['dummy_majority']['accuracy']}, "
              f"macro-F1={r['dummy_majority']['macro_f1']}\n  обучение {r['train_seconds']} c, "
              f"предсказание {r['predict_ms_per_text']} мс/текст\n")
    with open(os.path.join(a.out, "e1_tfidf_baseline.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("Результаты:", os.path.join(a.out, "e1_tfidf_baseline.json"))


if __name__ == "__main__":
    main()
