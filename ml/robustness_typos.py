"""Э8: устойчивость классификатора категорий к опечаткам.

Сравнивает текущую модель (обучена на чистых текстах) и модель, обученную с добавлением
искусственных опечаток. Проверка: тест A_grouped с разным уровнем шума и небольшой набор
написанных вручную «живых» обращений (data/realistic_check.csv).

Запуск из корня проекта:
    python ml/robustness_typos.py
    python ml/robustness_typos.py --save-model      (сохранить модель с опечатками рядом со старой)
    python ml/robustness_typos.py --save-base       (переобучить и сохранить рабочую модель)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore", message="Unknown solver options")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

from ml.common import grouped_split, load_dataset
from ml.train_tfidf_baseline import build_model

THRESHOLD = 0.7  # порог уверенности, как в backend/app/services/autoanalysis.py
NOISE_LEVELS = [0.0, 0.1, 0.2, 0.3]  # доля слов, в которых сделана опечатка
LETTERS = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"


def typo_word(word: str, rng: np.random.Generator) -> str:
    n = len(word)
    if n < 4:
        return word
    i = int(rng.integers(1, n - 1))
    op = rng.choice(["del", "swap", "sub", "dup"])
    if op == "del":
        return word[:i] + word[i + 1:]
    if op == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if op == "sub":
        return word[:i] + LETTERS[int(rng.integers(len(LETTERS)))] + word[i + 1:]
    return word[:i] + word[i] + word[i:]


def add_noise(texts, rate: float, seed: int) -> list[str]:
    rng = np.random.default_rng(seed)
    out = []
    for t in texts:
        words = str(t).split(" ")
        out.append(" ".join(typo_word(w, rng) if rng.random() < rate else w for w in words))
    return out


def evaluate(model, texts, y):
    proba = model.predict_proba(texts)
    classes = model.classes_
    pred = classes[proba.argmax(axis=1)]
    conf = proba.max(axis=1)
    y = np.asarray(y)
    auto = conf >= THRESHOLD
    wrong = pred != y
    return {
        "accuracy": round(float(accuracy_score(y, pred)), 4),
        "macro_f1": round(float(f1_score(y, pred, average="macro")), 4),
        "auto_share": round(float(auto.mean()), 4),
        # самое опасное: ошибка, которую система применила бы без проверки человеком
        "wrong_auto_share": round(float((wrong & auto).sum() / max(len(y), 1)), 4),
    }, pred, conf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/appeals_synthetic.csv")
    ap.add_argument("--check", default="data/realistic_check.csv")
    ap.add_argument("--out", default="ml/results")
    ap.add_argument("--models", default="ml/models")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--save-model", action="store_true")
    ap.add_argument("--save-base", action="store_true",
                    help="сохранить базовую модель как рабочую (старый файл переименуется в .old)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    best_c = 10
    e1 = os.path.join(a.out, "e1_tfidf_baseline.json")
    if os.path.exists(e1):
        best_c = json.load(open(e1, encoding="utf-8"))["A_grouped"]["best_C"]

    df = load_dataset(a.data)
    split = grouped_split(df, a.seed)
    tr, te = df.iloc[split["train"]], df.iloc[split["test"]]
    print(f"Обучающая часть {len(tr)}, тестовая {len(te)}, C = {best_c}")

    print("Обучаю базовую модель (чистые тексты)...")
    base = build_model(best_c).fit(tr["text"], tr["category"])

    print("Обучаю модель с опечатками (чистые тексты + две зашумлённые копии)...")
    aug_texts = list(tr["text"]) + add_noise(tr["text"], 0.15, a.seed + 1) + add_noise(tr["text"], 0.30, a.seed + 2)
    aug_labels = list(tr["category"]) * 3
    aug = build_model(best_c).fit(aug_texts, aug_labels)

    results = {"best_C": best_c, "threshold": THRESHOLD, "noise": {}, "realistic": {}}
    for rate in NOISE_LEVELS:
        noisy = add_noise(te["text"], rate, a.seed + 10) if rate > 0 else list(te["text"])
        rb, _, _ = evaluate(base, noisy, te["category"])
        ra, _, _ = evaluate(aug, noisy, te["category"])
        results["noise"][str(rate)] = {"base": rb, "aug": ra}
        print(f"шум {int(rate * 100):>2}%: базовая acc={rb['accuracy']:.3f} опасных={rb['wrong_auto_share']:.3f} | "
              f"с опечатками acc={ra['accuracy']:.3f} опасных={ra['wrong_auto_share']:.3f}")

    chk = pd.read_csv(a.check, encoding="utf-8")
    rb, pb, cb = evaluate(base, list(chk["text"]), chk["category"])
    ra, pa, ca = evaluate(aug, list(chk["text"]), chk["category"])
    results["realistic"] = {"n": len(chk), "base": rb, "aug": ra}
    print(f"\nЖивые обращения ({len(chk)} шт.): базовая acc={rb['accuracy']:.3f} опасных={rb['wrong_auto_share']:.3f} | "
          f"с опечатками acc={ra['accuracy']:.3f} опасных={ra['wrong_auto_share']:.3f}")
    rows = []
    for t, y, p1, c1, p2, c2 in zip(chk["text"], chk["category"], pb, cb, pa, ca):
        rows.append({"text": t, "expected": y, "base": p1, "base_conf": round(float(c1), 2),
                     "aug": p2, "aug_conf": round(float(c2), 2)})
        mark = lambda p: "ok " if p == y else "ОШ "
        print(f"  {mark(p1)}{p1:<11}{c1:.2f} | {mark(p2)}{p2:<11}{c2:.2f} | {t[:60]}")
    results["realistic"]["rows"] = rows

    with open(os.path.join(a.out, "e8_typos.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    xs = [int(r * 100) for r in NOISE_LEVELS]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for key, label, style in (("base", "обучена на чистых текстах", "o--"), ("aug", "обучена с опечатками", "s-")):
        axes[0].plot(xs, [results["noise"][str(r)][key]["accuracy"] for r in NOISE_LEVELS], style, label=label)
        axes[1].plot(xs, [results["noise"][str(r)][key]["wrong_auto_share"] for r in NOISE_LEVELS], style, label=label)
    axes[0].set_title("Точность при опечатках")
    axes[1].set_title("Доля ошибок, принятых без проверки")
    for ax in axes:
        ax.set_xlabel("Доля слов с опечаткой, %")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Точность")
    axes[1].set_ylabel("Доля от всех обращений")
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(os.path.join(a.out, "e8_typos.png"), dpi=150)

    if a.save_base:
        import shutil

        prod = os.path.join(a.models, "tfidf_logreg_A_grouped.joblib")
        if os.path.exists(prod):
            shutil.copy2(prod, prod + ".old")
        joblib.dump(base, prod)
        print("Рабочая модель обновлена:", prod)
    if a.save_model:
        path = os.path.join(a.models, "tfidf_logreg_A_grouped_typos.joblib")
        joblib.dump(aug, path)
        print("Модель сохранена:", path)
    print("Результаты:", os.path.join(a.out, "e8_typos.json"), "и e8_typos.png")


if __name__ == "__main__":
    main()
