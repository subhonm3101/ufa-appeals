"""Эксперимент Э7: порог уверенности для автоматического назначения категории (шаг 10.9).

Порог подбирается на валидационной выборке, на тестовой проверяется.
Правило: наименьший порог, при котором точность среди принятых автоматически не ниже цели.
Запуск из корня проекта:  python ml/threshold_analysis.py
"""
import argparse
import json
import os
import re
import warnings

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from common import grouped_split, load_dataset  # noqa: E402

VAGUE = [
    "Прошу помочь, у нас тут постоянно происходит что-то странное",
    "Хочу пожаловаться на безобразие в нашем районе",
    "Помогите разобраться с проблемой",
    "Здравствуйте, у меня вопрос по поводу города",
    "Сделайте уже что-нибудь наконец",
]


TOKEN = re.compile(r"(?u)\b\w\w+\b")


def word_vocab(model):
    """Однословные термины, которые модель видела при обучении."""
    word = dict(model.named_steps["tfidf"].transformer_list)["word"]
    return {t for t in word.vocabulary_ if " " not in t}


def known_share(vocab, text):
    """(доля слов, известных модели; число таких слов)."""
    tokens = TOKEN.findall(text.lower())
    if not tokens:
        return 0.0, 0
    known = sum(t in vocab for t in tokens)
    return known / len(tokens), known


def predict(model, texts):
    proba = model.predict_proba(texts)
    classes = np.array(model.classes_)
    return classes[proba.argmax(axis=1)], proba.max(axis=1)


def curve(y, pred, conf, grid):
    correct = pred == y
    rows = []
    for t in grid:
        mask = conf >= t
        rows.append({
            "threshold": round(float(t), 3),
            "coverage": float(mask.mean()),
            "accuracy_accepted": float(correct[mask].mean()) if mask.any() else None,
            "accepted": int(mask.sum()),
            "errors_accepted": int((~correct[mask]).sum()),
        })
    return rows


def choose(rows, target):
    for r in rows:
        if r["accuracy_accepted"] is not None and r["accuracy_accepted"] >= target:
            return r["threshold"]
    return None


def at(rows, t):
    return min(rows, key=lambda r: abs(r["threshold"] - t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/appeals_synthetic.csv")
    ap.add_argument("--model", default="ml/models/tfidf_logreg_A_grouped.joblib")
    ap.add_argument("--out", default="ml/results")
    ap.add_argument("--target", type=float, default=0.95)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    df = load_dataset(a.data)
    split = grouped_split(df, a.seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = joblib.load(a.model)

    grid = np.round(np.arange(0.20, 0.995, 0.01), 3)
    result = {"target_accuracy": a.target}
    curves = {}
    for part in ("val", "test"):
        sub = df.iloc[split[part]]
        pred, conf = predict(model, sub["text"].tolist())
        y = sub["category"].to_numpy()
        acc = float((pred == y).mean())
        curves[part] = curve(y, pred, conf, grid)
        result[part] = {
            "n": int(len(sub)),
            "accuracy": acc,
            "mean_confidence": float(conf.mean()),
            "overconfidence": float(conf.mean() - acc),
        }
    chosen = choose(curves["val"], a.target)
    result["chosen_threshold"] = chosen
    result["test_at_chosen"] = at(curves["test"], chosen) if chosen is not None else None
    result["test_at_0.55"] = at(curves["test"], 0.55)
    result["curves"] = curves

    vocab = word_vocab(model)
    test_texts = df.iloc[split["test"]]["text"].tolist()
    shares = np.array([known_share(vocab, t)[0] for t in test_texts])
    counts = np.array([known_share(vocab, t)[1] for t in test_texts])
    result["known_share_test"] = {
        "min": float(shares.min()),
        "p1": float(np.percentile(shares, 1)),
        "p5": float(np.percentile(shares, 5)),
        "median": float(np.median(shares)),
        "min_known_words": int(counts.min()),
        "p1_known_words": float(np.percentile(counts, 1)),
    }
    pred_v, conf_v = predict(model, VAGUE)
    result["vague_examples"] = [
        {"text": t, "category": str(c), "confidence": round(float(p), 3),
         "known_share": round(known_share(vocab, t)[0], 3), "known_words": known_share(vocab, t)[1]}
        for t, c, p in zip(VAGUE, pred_v, conf_v)
    ]

    with open(os.path.join(a.out, "e7_threshold.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    fig, ax = plt.subplots(figsize=(7, 4.2))
    th = [r["threshold"] for r in curves["test"]]
    ax.plot(th, [r["accuracy_accepted"] for r in curves["test"]], label="Точность среди принятых")
    ax.plot(th, [r["coverage"] for r in curves["test"]], label="Доля принятых автоматически")
    ax.axhline(a.target, color="gray", linestyle=":", linewidth=1)
    if chosen is not None:
        ax.axvline(chosen, color="red", linestyle="--", linewidth=1, label=f"Выбранный порог {chosen:.2f}")
    ax.axvline(0.55, color="orange", linestyle="--", linewidth=1, label="Прежний порог 0,55")
    ax.set_xlabel("Порог уверенности")
    ax.set_ylabel("Доля")
    ax.set_title("Выбор порога уверенности (тестовая выборка)")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(a.out, "e7_threshold.png"), dpi=160)

    print(f"val:  accuracy={result['val']['accuracy']:.3f}  mean conf={result['val']['mean_confidence']:.3f}")
    print(f"test: accuracy={result['test']['accuracy']:.3f}  mean conf={result['test']['mean_confidence']:.3f}")
    print(f"Chosen threshold (val, target {a.target}): {chosen}")
    print("\nTEST table: threshold | coverage | accuracy_accepted | errors")
    for t in (0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 0.95, chosen):
        if t is None:
            continue
        r = at(curves["test"], t)
        acc = "-" if r["accuracy_accepted"] is None else f"{r['accuracy_accepted']:.3f}"
        print(f"  {r['threshold']:.2f} | {r['coverage']:.3f} | {acc} | {r['errors_accepted']}")
    k = result["known_share_test"]
    print("\nKnown-words share on TEST texts: "
          f"min={k['min']:.2f} p1={k['p1']:.2f} p5={k['p5']:.2f} median={k['median']:.2f}; "
          f"known words: min={k['min_known_words']} p1={k['p1_known_words']:.0f}")
    print("\nVague examples (category, confidence, known share, known words):")
    for e in result["vague_examples"]:
        print(f"  {e['category']:12s} {e['confidence']:.2f}  {e['known_share']:.2f}  {e['known_words']}  {e['text'][:45]}")
    print("\nSaved:", os.path.join(a.out, "e7_threshold.json"), "and e7_threshold.png")


if __name__ == "__main__":
    main()
