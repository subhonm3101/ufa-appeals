"""Показывает кластер, координаты и приоритет обращения. Запуск из корня проекта:

    python backend/scripts/show_appeal.py UFA-2026-005412
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sqlalchemy import text

from app.db import SessionLocal

if len(sys.argv) != 2:
    sys.exit("Использование: python backend/scripts/show_appeal.py UFA-2026-000001")

with SessionLocal() as s:
    a = s.execute(text(
        "SELECT id, status, category_id, district_id, lat, lon, cluster_id, needs_review "
        "FROM appeals WHERE public_number = :n"), {"n": sys.argv[1].strip().upper()}).first()
    if a is None:
        sys.exit("Обращение не найдено")
    print("обращение:", dict(a._mapping))
    if a.cluster_id is None:
        sys.exit("кластера нет")
    cl = s.execute(text(
        "SELECT status, category_id, district_id, centroid_lat, centroid_lon, appeals_count "
        "FROM clusters WHERE id = :c"), {"c": a.cluster_id}).first()
    print("кластер:  ", dict(cl._mapping))
    for r in s.execute(text(
            "SELECT method, score, as_of FROM priority_scores WHERE cluster_id = :c ORDER BY as_of DESC"),
            {"c": a.cluster_id}):
        print("приоритет:", r.method, r.score, r.as_of)
