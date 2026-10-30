"""Шаг 5.3: выгрузка состава кластеров (cluster_id -> external_id обращений) для текстовых моделей.

    python backend/scripts/export_cluster_members.py
"""
import argparse
import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sqlalchemy import text as sql

from app.db import SessionLocal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-10-27T12:00:00+00:00")
    ap.add_argument("--out", default="data/labeling/cluster_members.csv")
    a = ap.parse_args()
    with SessionLocal() as s:
        rows = s.execute(sql(
            "SELECT cluster_id, external_id FROM appeals "
            "WHERE cluster_id IS NOT NULL AND external_id IS NOT NULL AND created_at <= :a ORDER BY cluster_id, created_at"),
            {"a": datetime.fromisoformat(a.as_of)}).fetchall()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cluster_id", "external_id"])
        w.writerows(rows)
    print(f"Выгружено {len(rows)} обращений -> {a.out}")


if __name__ == "__main__":
    main()
