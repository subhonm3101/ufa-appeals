"""Шаг 5.2 (часть 3а): экспертная разметка против формулы rules_v1 (эксперимент Э3, часть 1).

    python ml/analyze_labels.py
Читает data/labeling/{items_key.csv, ratings.csv, priority_table.csv}.
Пишет ml/results/e3_expert_agreement.json, e3_expert_table.md и data/labeling/disagreements.csv.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, spearmanr
from sklearn.metrics import cohen_kappa_score, ndcg_score

COMP = ["urgency", "significance", "scale", "age", "dynamics"]
NAMES = {"score": "Итоговый score (rules_v1)", "urgency": "Только срочность", "significance": "Только значимость",
         "scale": "Только масштаб", "age": "Только возраст", "dynamics": "Только динамика"}


def gains(r):
    return np.power(2.0, np.asarray(r, float)) - 1


def ndcg(y, s, k):
    return float(ndcg_score([gains(y)], [np.asarray(s, float)], k=k))


def rand_ndcg(y, k, rng, n=2000):
    g = gains(y)
    return float(np.mean([ndcg_score([g], [rng.random(len(g))], k=k) for _ in range(n)]))


def safe_rho(x, y):
    if np.nanstd(x) == 0:
        return float("nan")
    return float(spearmanr(x, y)[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/labeling")
    ap.add_argument("--out", default="ml/results")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--invert", action="store_true", help="диагностика: 1 и 5 меняются местами")
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)

    key = pd.read_csv(os.path.join(a.dir, "items_key.csv"))
    rat = pd.read_csv(os.path.join(a.dir, "ratings.csv"), encoding="utf-8-sig")
    if a.invert:
        rat["rating"] = 6 - rat["rating"]
    tab = pd.read_csv(os.path.join(a.dir, "priority_table.csv"), encoding="utf-8-sig").rename(columns={"score": "score_db"})

    df = key.merge(rat[["item_id", "rating", "seconds"]], on="item_id", how="left")
    miss = int(df["rating"].isna().sum())
    if miss:
        sys.exit(f"Нет оценок для {miss} карточек из {len(df)}. Доразметь и скачай ratings.csv заново.")
    if not df["rating"].between(1, 5).all():
        sys.exit("В ratings.csv есть оценки вне 1..5")
    df = df.sort_values("item_id")
    res = {"n_items": int(len(df)), "rating_counts": {int(k): int(v) for k, v in df["rating"].value_counts().sort_index().items()},
           "median_seconds_per_item": float(df["seconds"].median())}

    # 1) устойчивость оценок эксперта: один и тот же кластер показан дважды
    pairs = [g["rating"].to_numpy() for _, g in df.groupby("cluster_id") if len(g) == 2]
    if len(pairs) >= 5:
        p1, p2 = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
        res["repeat"] = {"n": len(pairs),
                         "exact_agreement": round(float((p1 == p2).mean()), 3),
                         "within_one": round(float((np.abs(p1 - p2) <= 1).mean()), 3),
                         "weighted_kappa": round(float(cohen_kappa_score(p1, p2, weights="quadratic", labels=[1, 2, 3, 4, 5])), 3)}

    # 2) оценка кластера: среднее по его показам
    cl = df.groupby("cluster_id").agg(rating=("rating", "mean"), score=("score", "first")).reset_index()
    cl = cl.merge(tab, on="cluster_id", how="left")
    if cl["score_db"].isna().any():
        print(f"Внимание: для {int(cl['score_db'].isna().sum())} кластеров нет строки в priority_table.csv")
    elif (cl["score"] - cl["score_db"]).abs().max() > 0.01:
        print("Внимание: score в items_key.csv и в БД различаются, возможно, расчёт перезаписан другими весами")
    y, s, n = cl["rating"].to_numpy(), cl["score"].to_numpy(), len(cl)
    res["n_clusters"] = int(n)

    rho = float(spearmanr(s, y)[0])
    boots = [safe_rho(s[i], y[i]) for i in rng.integers(0, n, (2000, n))]
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    res["score_vs_expert"] = {"spearman": round(rho, 3), "ci95": [round(float(lo), 3), round(float(hi), 3)],
                              "kendall_tau": round(float(kendalltau(s, y)[0]), 3)}

    # 3) таблица «чем ранжировать»: итоговый score и каждый компонент отдельно
    rows = {}
    for name in ["score"] + COMP:
        v = cl[name].to_numpy(float) if name in cl else None
        if v is None or np.isnan(v).any():
            continue
        rows[name] = {"spearman": round(safe_rho(v, y), 3), "ndcg10": round(ndcg(y, v, 10), 3), "ndcg20": round(ndcg(y, v, 20), 3)}
    rows["random"] = {"spearman": 0.0, "ndcg10": round(rand_ndcg(y, 10, rng), 3), "ndcg20": round(rand_ndcg(y, 20, rng), 3)}
    res["rankers"] = rows

    # 4) монотонность: средняя оценка эксперта по пятым долям score
    cl["bin"] = pd.qcut(cl["score"].rank(method="first"), 5, labels=False) + 1
    res["mean_rating_by_score_quintile"] = {int(k): round(float(v), 2) for k, v in cl.groupby("bin")["rating"].mean().items()}

    # 5) самые большие расхождения (по перцентилям рангов)
    cl["pct_score"] = cl["score"].rank(pct=True)
    cl["pct_expert"] = cl["rating"].rank(pct=True)
    cl["diff"] = cl["pct_score"] - cl["pct_expert"]
    os.makedirs(a.out, exist_ok=True)
    cols = ["cluster_id", "rating", "score", "diff", "urgency", "significance", "scale", "age", "dynamics",
            "appeals", "category", "example"]
    cl.sort_values("diff", ascending=False)[[c for c in cols if c in cl]].to_csv(
        os.path.join(a.dir, "disagreements.csv"), index=False, encoding="utf-8-sig")

    with open(os.path.join(a.out, "e3_expert_agreement.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    lines = ["| Чем ранжируем | Спирмен | NDCG@10 | NDCG@20 |", "|---|---|---|---|"]
    for k, v in rows.items():
        lines.append(f"| {NAMES.get(k, 'Случайный порядок')} | {v['spearman']:.3f} | {v['ndcg10']:.3f} | {v['ndcg20']:.3f} |")
    with open(os.path.join(a.out, "e3_expert_table.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Карточек: {res['n_items']}, кластеров: {n}, медиана времени на карточку: {res['median_seconds_per_item']:.0f} с")
    print("Распределение оценок:", res["rating_counts"])
    if "repeat" in res:
        r = res["repeat"]
        print(f"\nУстойчивость (n={r['n']} повторов): совпало {r['exact_agreement']:.0%}, "
              f"в пределах ±1: {r['within_one']:.0%}, взвешенная каппа {r['weighted_kappa']}")
    sv = res["score_vs_expert"]
    print(f"\nScore против эксперта: Спирмен {sv['spearman']} (95% ДИ {sv['ci95'][0]}..{sv['ci95'][1]}), тау Кендалла {sv['kendall_tau']}")
    print("\n" + "\n".join(lines))
    print("\nСредняя оценка эксперта по пятым долям score (1 = низкий score):", res["mean_rating_by_score_quintile"])
    show = cl.sort_values("diff", ascending=False)
    for title, part in (("Формула ставит ВЫШЕ, чем эксперт", show.head(6)), ("Формула ставит НИЖЕ, чем эксперт", show.tail(6))):
        print(f"\n{title}:")
        for _, r in part.iterrows():
            print(f"  эксперт {r['rating']:.1f} | score {r['score']:5.1f} | n={int(r.get('appeals', 0))} | {r.get('example', '')}")
    print("\nСохранено:", os.path.join(a.out, "e3_expert_agreement.json"), "и e3_expert_table.md; расхождения:",
          os.path.join(a.dir, "disagreements.csv"))


if __name__ == "__main__":
    main()