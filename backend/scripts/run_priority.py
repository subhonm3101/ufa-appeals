import argparse
import json
import os
import statistics
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.db import SessionLocal
from app.services.priority_features import COMPONENTS, DEFAULT_CONFIG, compute_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-10-27T12:00:00+00:00")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--weights", default=None)
    a = ap.parse_args()

    cfg = DEFAULT_CONFIG
    if a.weights:
        with open(a.weights, "r", encoding="utf-8") as f:
            model = json.load(f)
        weights = model["weights"]
        missing = set(COMPONENTS) - set(weights)
        if missing:
            raise ValueError(f"В файле отсутствуют веса: {sorted(missing)}")
        cfg = replace(cfg, method=model.get("method", "rules_v2"), weights=weights)

    as_of = datetime.fromisoformat(a.as_of)
    with SessionLocal() as s:
        res = compute_all(s, as_of, cfg, save=a.save)

    if not res:
        sys.exit("Нет кластеров на эту дату")

    scores = [r["score"] for r in res]
    print(f"Дата расчёта: {as_of:%Y-%m-%d %H:%M}, активных кластеров: {len(res)}")
    print(f"score: min {min(scores):.1f}, медиана {statistics.median(scores):.1f}, макс {max(scores):.1f}")

    lv = Counter(r["factors"]["raw"]["urgency_level"] for r in res)
    print("Срочность по кластерам: " + ", ".join(f"{k}: {lv[k]}" for k in sorted(lv)))

    print(f"\nТоп-{a.top}:")
    print("  #  score  " + "  ".join(f"{c[:5]:>5}" for c in COMPONENTS) + "  n  категория   пример")
    for i, r in enumerate(res[:a.top], 1):
        f = r["factors"]
        comp = "  ".join(f"{f['components'][c]:5.2f}" for c in COMPONENTS)
        print(f"{i:3d}  {r['score']:5.1f}  {comp}  {f['raw']['appeals']:2d}  {f['raw']['category']:<11} {r['example']}")

    if a.save:
        print(f"\nЗаписано в priority_scores: {len(res)} строк (method={cfg.method})")


if __name__ == "__main__":
    main()
