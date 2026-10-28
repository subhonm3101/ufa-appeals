"""Э1, часть 2: классификатор на векторах rubert-tiny2 + логистическая регрессия, шаг 4.2.

Запуск из корня проекта:
    python ml/train_embedding_clf.py --data data/appeals_synthetic.csv --out ml/results --models ml/models
Деление на выборки то же, что в 4.1 (сценарии A, B, C), поэтому результаты можно сравнивать напрямую.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import joblib
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from ml.common import assert_no_group_leak, load_dataset, split_summary
from ml.embeddings import DEFAULT_MODEL, encode_texts
from ml.train_tfidf_baseline import C_GRID, SCENARIOS, plot_cm


def run_scenario(key, title, fn, df, X, out_dir, models_dir, seed, model_name):
    split = fn(df, seed)
    leak = False
    try:
        assert_no_group_leak(df, split)
    except AssertionError:
        leak = True
    tr, va, te = split["train"], split["val"], split["test"]
    ytr, yva, yte = (df["category"].values[i] for i in (tr, va, te))

    dpred = DummyClassifier(strategy="most_frequent").fit(X[tr], ytr).predict(X[te])

    best, grid = None, {}
    for c in C_GRID:
        m = LogisticRegression(C=c, class_weight="balanced", max_iter=3000).fit(X[tr], ytr)
        f1 = f1_score(yva, m.predict(X[va]), average="macro")
        grid[str(c)] = round(f1, 4)
        if best is None or f1 > best[0]:
            best = (f1, c)
    best_c = best[1]

    t0 = time.perf_counter()
    clf = LogisticRegression(C=best_c, class_weight="balanced", max_iter=3000).fit(X[tr], ytr)
    train_s = time.perf_counter() - t0
    pred = clf.predict(X[te])

    labels = sorted(df["category"].unique())
    cm = confusion_matrix(yte, pred, labels=labels)
    rep = classification_report(yte, pred, labels=labels, output_dict=True, zero_division=0)
    per_sub = (df.iloc[te].assign(ok=(pred == yte)).groupby(["category", "subtopic"])["ok"]
               .agg(["mean", "size"]).rename(columns={"mean": "accuracy", "size": "n"}).round(3).reset_index())
    res = {
        "scenario": title, "model": model_name, "group_leak_between_train_test": leak,
        "split": split_summary(df, split).to_dict("records"),
        "best_C": best_c, "val_macro_f1_by_C": grid,
        "test": {"accuracy": round(accuracy_score(yte, pred), 4),
                 "macro_f1": round(f1_score(yte, pred, average="macro"), 4),
                 "weighted_f1": round(f1_score(yte, pred, average="weighted"), 4)},
        "dummy_majority": {"accuracy": round(accuracy_score(yte, dpred), 4),
                           "macro_f1": round(f1_score(yte, dpred, average="macro", zero_division=0), 4)},
        "per_class": {k: {m: round(v, 4) for m, v in rep[k].items()} for k in labels},
        "confusion_matrix": {"labels": labels, "matrix": cm.tolist()},
        "worst_subtopics": per_sub.sort_values("accuracy").head(8).to_dict("records"),
        "train_seconds": round(train_s, 2),
    }
    plot_cm(cm, labels, f"rubert-tiny2 + LogReg\n{title}\nmacro-F1 = {res['test']['macro_f1']}",
            os.path.join(out_dir, f"cm_emb_{key}.png"))
    joblib.dump(clf, os.path.join(models_dir, f"emb_logreg_{key}.joblib"))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/appeals_synthetic.csv")
    ap.add_argument("--out", default="ml/results")
    ap.add_argument("--models", default="ml/models")
    ap.add_argument("--cache", default="ml/cache")
    ap.add_argument("--model-name", default=DEFAULT_MODEL, help="имя модели на Hugging Face или путь к папке")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--tag", default="e1_embedding_rubert", help="имя файла результатов без расширения")
    a = ap.parse_args()
    for d in (a.out, a.models):
        os.makedirs(d, exist_ok=True)

    df = load_dataset(a.data)
    print(f"Данные: {len(df)} обращений. Считаю векторы ({a.model_name}); первый раз это несколько минут...")
    t0 = time.perf_counter()
    X = encode_texts(df["text"].tolist(), a.model_name, cache_dir=a.cache)
    print(f"Векторы: {X.shape}, {time.perf_counter() - t0:.0f} c\n")

    sample = df["text"].iloc[:200].tolist()
    t0 = time.perf_counter()
    encode_texts(sample, a.model_name)
    enc_ms = (time.perf_counter() - t0) / len(sample) * 1000

    base_path = os.path.join(a.out, "e1_tfidf_baseline.json")
    base = json.load(open(base_path, encoding="utf-8")) if os.path.exists(base_path) else {}

    results = {}
    for key, (title, fn) in SCENARIOS.items():
        r = run_scenario(key, title, fn, df, X, a.out, a.models, a.seed, a.model_name)
        r["encode_ms_per_text_incl_load"] = round(enc_ms, 2)
        results[key] = r
        line = (f"{title}\n  rubert-tiny2 + LogReg: accuracy={r['test']['accuracy']}, "
                f"macro-F1={r['test']['macro_f1']} (C={r['best_C']})")
        if key in base:
            line += (f"\n  TF-IDF + LogReg (4.1):  accuracy={base[key]['test']['accuracy']}, "
                     f"macro-F1={base[key]['test']['macro_f1']}")
        print(line + "\n")
    print(f"Векторизация: {enc_ms:.1f} мс/текст (с учётом разовой загрузки модели)")
    with open(os.path.join(a.out, f"{a.tag}.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("Результаты:", os.path.join(a.out, f"{a.tag}.json"))


if __name__ == "__main__":
    main()
