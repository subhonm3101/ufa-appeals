"""Шаг 5.2 (часть 3): два раунда разметки -> итоговая экспертная оценка и сравнение с формулой rules_v1.

    python ml/analyze_rounds.py

Читает:  data/labeling/{items_key,ratings,priority_table}.csv   (раунд 1)
         data/labeling_r2/{items_key,ratings}.csv               (раунд 2, часть тех же кластеров)
Пишет:   data/labeling/expert_labels.csv       итоговые оценки кластеров (для БД и шага 5.3)
         data/labeling/disagreements.csv       где формула и эксперт расходятся сильнее всего
         ml/results/e3_expert_agreement.json, e3_expert_table.md

Главный вопрос: в раунде 1 шкала была перевёрнута? Проверяем по раунду 2: если новые оценки
отрицательно коррелируют с прежними, раунд 1 надо перевернуть (6 - оценка). Решение принимается по данным.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, spearmanr
from sklearn.metrics import cohen_kappa_score

from ml.e3_metrics import boot_rho_ci, ndcg, rand_ndcg, safe_rho

COMP = ["urgency", "significance", "scale", "age", "dynamics"]
NAMES = {"score": "Итоговый score (rules_v1)", "urgency": "Только срочность", "significance": "Только значимость",
         "scale": "Только масштаб", "age": "Только возраст", "dynamics": "Только динамика",
         "random": "Случайный порядок"}


def load_round(d: str, allow_missing: bool = False) -> pd.DataFrame:
    kp, rp = os.path.join(d, "items_key.csv"), os.path.join(d, "ratings.csv")
    for p in (kp, rp):
        if not os.path.exists(p):
            sys.exit(f"Нет файла {p}")
    key = pd.read_csv(kp)
    rat = pd.read_csv(rp, encoding="utf-8-sig")
    df = key.merge(rat[["item_id", "rating", "seconds"]], on="item_id", how="left").sort_values("item_id")
    miss = int(df["rating"].isna().sum())
    if miss and not allow_missing:
        sys.exit(f"{d}: нет оценок для {miss} карточек из {len(df)}. Доразметь и скачай ratings.csv заново.")
    if miss:
        print(f"Внимание: {d}: не размечено {miss} из {len(df)} карточек, они пропущены")
        df = df.dropna(subset=["rating"])
    if not df["rating"].between(1, 5).all():
        sys.exit(f"{d}: в ratings.csv есть оценки вне 1..5")
    return df


def per_cluster(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("cluster_id")
    return pd.DataFrame({"first": g["rating"].first(), "mean": g["rating"].mean(),
                         "score": g["score"].first(), "order": g["item_id"].first()})


def agreement(a, b) -> dict:
    a, b = np.asarray(a, int), np.asarray(b, int)
    return {"exact": round(float((a == b).mean()), 3), "within_one": round(float((np.abs(a - b) <= 1).mean()), 3),
            "weighted_kappa": round(float(cohen_kappa_score(a, b, weights="quadratic", labels=[1, 2, 3, 4, 5])), 3)}


def evaluate(cl: pd.DataFrame, ycol: str, rng) -> dict:
    y, s, n = cl[ycol].to_numpy(float), cl["score"].to_numpy(float), len(cl)
    rho, lo, hi = boot_rho_ci(s, y, rng)
    rankers = {}
    for name in ["score"] + COMP:
        if name not in cl or cl[name].isna().any():
            continue
        v = cl[name].to_numpy(float)
        rankers[name] = {"spearman": round(safe_rho(v, y), 3), "ndcg10": round(ndcg(y, v, 10), 3),
                         "ndcg20": round(ndcg(y, v, 20), 3)}
    rankers["random"] = {"spearman": 0.0, "ndcg10": round(rand_ndcg(y, 10, rng), 3),
                         "ndcg20": round(rand_ndcg(y, 20, rng), 3)}
    q = pd.qcut(pd.Series(s).rank(method="first"), 5, labels=False) + 1
    quint = {int(k): round(float(v), 2) for k, v in pd.Series(y).groupby(q.to_numpy()).mean().items()}
    return {"n_clusters": int(n), "spearman": round(rho, 3), "ci95": [round(lo, 3), round(hi, 3)],
            "kendall_tau": round(float(kendalltau(s, y)[0]), 3), "rankers": rankers,
            "mean_rating_by_score_quintile": quint}


def table_md(res: dict) -> str:
    lines = ["| Чем ранжируем | Спирмен | NDCG@10 | NDCG@20 |", "|---|---|---|---|"]
    for k, v in res["rankers"].items():
        lines.append(f"| {NAMES[k]} | {v['spearman']:.3f} | {v['ndcg10']:.3f} | {v['ndcg20']:.3f} |")
    return "\n".join(lines)


def print_eval(title: str, res: dict) -> None:
    print(f"\n=== {title} (кластеров: {res['n_clusters']}) ===")
    print(f"Score против эксперта: Спирмен {res['spearman']} (95% ДИ {res['ci95'][0]}..{res['ci95'][1]}), "
          f"тау Кендалла {res['kendall_tau']}")
    print(table_md(res))
    print("Средняя оценка эксперта по пятым долям score (1 = низкий score):", res["mean_rating_by_score_quintile"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir1", default="data/labeling")
    ap.add_argument("--dir2", default="data/labeling_r2")
    ap.add_argument("--out", default="ml/results")
    ap.add_argument("--r1-orient", default="auto", choices=["auto", "keep", "invert"],
                    help="как читать раунд 1: auto - по данным раунда 2")
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)

    d1, d2 = load_round(a.dir1), load_round(a.dir2, allow_missing=True)
    r1, r2 = per_cluster(d1), per_cluster(d2)
    res = {"round1": {"cards": int(len(d1)), "clusters": int(len(r1)),
                      "median_seconds": float(d1["seconds"].median()),
                      "rating_counts": {int(k): int(v) for k, v in d1["rating"].value_counts().sort_index().items()}},
           "round2": {"cards": int(len(d2)), "clusters": int(len(r2)),
                      "median_seconds": float(d2["seconds"].median()),
                      "rating_counts": {int(k): int(v) for k, v in d2["rating"].value_counts().sort_index().items()}}}
    print(f"Раунд 1: {res['round1']['cards']} карточек, медиана {res['round1']['median_seconds']:.0f} с, "
          f"оценки {res['round1']['rating_counts']}")
    print(f"Раунд 2: {res['round2']['cards']} карточек, медиана {res['round2']['median_seconds']:.0f} с, "
          f"оценки {res['round2']['rating_counts']}")

    # 1) сравнение раундов на общих кластерах
    c = r1.join(r2[["first"]].rename(columns={"first": "r2"}), how="inner").sort_values("order")
    if len(c) < 20:
        sys.exit(f"Общих кластеров в двух раундах всего {len(c)}, для проверки нужно хотя бы 20")
    rho, p = spearmanr(c["mean"], c["r2"])
    half = len(c) // 2
    rho_a = safe_rho(c["mean"].iloc[:half], c["r2"].iloc[:half])
    rho_b = safe_rho(c["mean"].iloc[half:], c["r2"].iloc[half:])
    ag_keep = agreement(c["first"], c["r2"])
    ag_inv = agreement(6 - c["first"], c["r2"])
    res["rounds_comparison"] = {"common_clusters": int(len(c)), "spearman_r1_vs_r2": round(float(rho), 3),
                                "p_value": float(p), "spearman_first_half": round(rho_a, 3),
                                "spearman_second_half": round(rho_b, 3),
                                "agreement_if_r1_kept": ag_keep, "agreement_if_r1_inverted": ag_inv}
    print(f"\n=== Раунд 1 против раунда 2 (общих кластеров: {len(c)}) ===")
    print(f"Спирмен между раундами: {rho:.3f} (p={p:.2g}); первая половина раунда 1: {rho_a:.3f}, вторая: {rho_b:.3f}")
    print(f"Если раунд 1 оставить как есть:  совпало {ag_keep['exact']:.0%}, ±1: {ag_keep['within_one']:.0%}, "
          f"взвешенная каппа {ag_keep['weighted_kappa']}")
    print(f"Если раунд 1 перевернуть (6-x):  совпало {ag_inv['exact']:.0%}, ±1: {ag_inv['within_one']:.0%}, "
          f"взвешенная каппа {ag_inv['weighted_kappa']}")

    if a.r1_orient == "auto":
        if np.isnan(rho) or abs(rho) < 0.2:
            sys.exit("Связь между раундами слабая (|Спирмен| < 0.2), по данным шкалу определить нельзя.\n"
                     "Если знаешь, как ставил оценки в раунде 1, запусти с --r1-orient keep или --r1-orient invert.")
        orient = "invert" if rho < 0 else "keep"
    else:
        orient = a.r1_orient
    invert = orient == "invert"
    ok = (ag_inv["weighted_kappa"] > ag_keep["weighted_kappa"]) == invert
    print(f"\nВывод: раунд 1 читаем как «{'перевёрнутый' if invert else 'как есть'}» (режим {a.r1_orient})."
          + ("" if ok else " ВНИМАНИЕ: каппа указывает в другую сторону, результат неоднозначный."))
    res["round1_orientation"] = orient

    # 2) итоговая оценка кластера
    r1o = (6 - r1["mean"]) if invert else r1["mean"]
    cl = pd.DataFrame({"r1": r1o, "score": r1["score"]})
    cl["r2"] = r2["first"].reindex(cl.index)
    cl["rating"] = cl[["r1", "r2"]].mean(axis=1)
    cl["n_rounds"] = cl["r2"].notna().astype(int) + 1
    cl = cl.reset_index()
    tab = pd.read_csv(os.path.join(a.dir1, "priority_table.csv"), encoding="utf-8-sig").rename(columns={"score": "score_db"})
    cl = cl.merge(tab, on="cluster_id", how="left")
    if cl["score_db"].isna().any():
        print(f"Внимание: для {int(cl['score_db'].isna().sum())} кластеров нет строки в priority_table.csv")
    elif (cl["score"] - cl["score_db"]).abs().max() > 0.01:
        print("Внимание: score в items_key.csv и в БД различаются, возможно, приоритет пересчитан другими весами")

    labels = cl[["cluster_id", "rating", "r1", "r2", "n_rounds"]].rename(columns={"r1": "r1_oriented"})
    labels["orientation"] = orient
    labels.to_csv(os.path.join(a.dir1, "expert_labels.csv"), index=False, encoding="utf-8")

    # 3) формула против эксперта: на всех кластерах и только по «чистому» раунду 2
    res["combined"] = evaluate(cl, "rating", rng)
    print_eval("Формула rules_v1 против итоговой разметки (раунд 1 с поправкой на шкалу + раунд 2)", res["combined"])
    sub = cl[cl["r2"].notna()].copy()
    res["round2_only"] = evaluate(sub, "r2", rng)
    print_eval("Формула rules_v1 против только раунда 2 (медленная разметка с подписанными кнопками)", res["round2_only"])

    # 4) расхождения
    cl["pct_score"] = cl["score"].rank(pct=True)
    cl["pct_expert"] = cl["rating"].rank(pct=True)
    cl["diff"] = cl["pct_score"] - cl["pct_expert"]
    cols = ["cluster_id", "rating", "score", "diff"] + COMP + ["appeals", "category", "example"]
    show = cl.sort_values("diff", ascending=False)
    show[[x for x in cols if x in show]].to_csv(os.path.join(a.dir1, "disagreements.csv"), index=False,
                                                encoding="utf-8-sig")
    for title, part in (("Формула ставит ВЫШЕ, чем эксперт", show.head(6)),
                        ("Формула ставит НИЖЕ, чем эксперт", show.tail(6))):
        print(f"\n{title}:")
        for _, r in part.iterrows():
            print(f"  эксперт {r['rating']:.1f} | score {r['score']:5.1f} | n={int(r.get('appeals', 0))} | {r.get('example', '')}")

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "e3_expert_agreement.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "e3_expert_table.md"), "w", encoding="utf-8") as f:
        f.write("**Итоговая разметка (все кластеры)**\n\n" + table_md(res["combined"]) +
                "\n\n**Только раунд 2**\n\n" + table_md(res["round2_only"]) + "\n")
    print(f"\nСохранено: {os.path.join(a.dir1, 'expert_labels.csv')} ({len(labels)} кластеров), "
          f"disagreements.csv, {a.out}/e3_expert_agreement.json, e3_expert_table.md")


if __name__ == "__main__":
    main()
