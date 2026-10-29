"""Шаг 5.1 (часть 2г): приоритет кластеров на дату as_of, топ с разбором по компонентам.

    python backend/scripts/run_priority.py                  # только показать
    python backend/scripts/run_priority.py --save           # и записать в priority_scores
"""
import argparse
import os
import statistics
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.db import SessionLocal
from app.services.priority_features import COMPONENTS, DEFAULT_CONFIG, compute_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-10-27T12:00:00+00:00")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()
    as_of = datetime.fromisoformat(a.as_of)

    with SessionLocal() as s:
        res = compute_all(s, as_of, DEFAULT_CONFIG, save=a.save)
    if not res:
        sys.exit("Нет активных кластеров на эту дату")

    scores = [r["score"] for r in res]
    print(f"Дата расчёта: {as_of:%Y-%m-%d %H:%M}, активных кластеров: {len(res)}")
    print(f"score: min {min(scores):.1f}, медиана {statistics.median(scores):.1f}, макс {max(scores):.1f}")
    lv = Counter(r["factors"]["raw"]["urgency_level"] for r in res)
    print("Срочность по кластерам (уровень: число): " + ", ".join(f"{k}: {lv[k]}" for k in sorted(lv)))
    sizes = Counter(r["factors"]["raw"]["appeals"] for r in res)
    print("Размер кластера (обращений: число): " + ", ".join(f"{k}: {sizes[k]}" for k in sorted(sizes)))
    print(f"\nТоп-{a.top}:")
    print("  #  score  " + "  ".join(f"{c[:5]:>5}" for c in COMPONENTS) + "  n  категория   пример")
    for i, r in enumerate(res[:a.top], 1):
        f = r["factors"]
        comp = "  ".join(f"{f['components'][c]:5.2f}" for c in COMPONENTS)
        print(f"{i:3d}  {r['score']:5.1f}  {comp}  {f['raw']['appeals']:2d}  {f['raw']['category']:<11} {r['example']}")
    print("\nСамые низкие 3:")
    for r in res[-3:]:
        f = r["factors"]
        print(f"     {r['score']:5.1f}  n={f['raw']['appeals']}  {f['raw']['category']:<11} {r['example']}")
    if a.save:
        print(f"\nЗаписано в priority_scores: {len(res)} строк (method={DEFAULT_CONFIG.method})")


if __name__ == "__main__":
    main()