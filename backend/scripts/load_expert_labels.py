"""Шаг 5.2: загрузка итоговой экспертной разметки в таблицу expert_labels.

    python backend/scripts/load_expert_labels.py            # читает data/labeling/expert_labels.csv
Повторный запуск безопасен: строки с тем же as_of и source заменяются.
"""
import argparse
import csv
import os
import sys
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

DEFAULT_DSN = os.environ.get("APPEALS_DSN", "postgresql://appeals:appeals@127.0.0.1:5433/appeals")


def num(x):
    x = (x or "").strip()
    return float(x) if x else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/labeling/expert_labels.csv")
    ap.add_argument("--as-of", default="2026-10-27T12:00:00+00:00")
    ap.add_argument("--source", default="self_two_rounds")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    a = ap.parse_args()
    as_of = datetime.fromisoformat(a.as_of)

    with open(a.csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("expert_labels.csv пуст")
    vals = [(int(r["cluster_id"]), num(r["rating"]), num(r["r1_oriented"]), num(r["r2"]),
             r["orientation"], as_of, a.source) for r in rows]

    conn = psycopg2.connect(a.dsn)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM expert_labels WHERE as_of = %s AND source = %s", (as_of, a.source))
            execute_values(cur, "INSERT INTO expert_labels (cluster_id, rating, r1, r2, orientation, as_of, source) VALUES %s",
                           vals)
            cur.execute("SELECT count(*), count(r2), round(avg(rating)::numeric, 2) FROM expert_labels "
                        "WHERE as_of = %s AND source = %s", (as_of, a.source))
            total, with_r2, avg = cur.fetchone()
        print(f"В expert_labels: {total} кластеров, из них с двумя раундами: {with_r2}, средняя оценка {avg}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
