"""Шаг 5.2 (часть 3а): выгрузка сохранённого приоритета rules_v1 в CSV для анализа.

    python backend/scripts/export_priority_table.py
Нужен предварительный запуск run_priority.py --save для той же даты.
"""
import argparse
import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sqlalchemy import text as sql

from app.db import SessionLocal

Q = """
SELECT ps.cluster_id, ps.score,
  CAST(ps.factors->'components'->>'urgency' AS double precision),
  CAST(ps.factors->'components'->>'significance' AS double precision),
  CAST(ps.factors->'components'->>'scale' AS double precision),
  CAST(ps.factors->'components'->>'age' AS double precision),
  CAST(ps.factors->'components'->>'dynamics' AS double precision),
  CAST(ps.factors->'raw'->>'appeals' AS integer),
  CAST(ps.factors->'raw'->>'urgency_level' AS integer),
  ps.factors->'raw'->>'category',
  (SELECT left(a.text, 110) FROM appeals a WHERE a.cluster_id = ps.cluster_id ORDER BY a.created_at LIMIT 1)
FROM priority_scores ps
WHERE ps.method = :m AND ps.as_of = :a
ORDER BY ps.score DESC
"""
COLS = ["cluster_id", "score", "urgency", "significance", "scale", "age", "dynamics",
        "appeals", "urgency_level", "category", "example"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-10-27T12:00:00+00:00")
    ap.add_argument("--method", default="rules_v1")
    ap.add_argument("--out", default="data/labeling/priority_table.csv")
    a = ap.parse_args()
    with SessionLocal() as s:
        rows = s.execute(sql(Q), {"m": a.method, "a": datetime.fromisoformat(a.as_of)}).fetchall()
    if not rows:
        sys.exit("В priority_scores нет строк. Сначала: python backend\\scripts\\run_priority.py --save")
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(rows)
    print(f"Выгружено {len(rows)} кластеров -> {a.out}")


if __name__ == "__main__":
    main()