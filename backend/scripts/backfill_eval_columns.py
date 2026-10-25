"""Дозаполняет problem_id и subtopic у уже загруженных обращений (эталон для экспериментов).

Нужно один раз после миграции 0002, потому что обращения были загружены до появления этих колонок.
Запуск из корня проекта:
    python backend/scripts/backfill_eval_columns.py data/appeals_synthetic.csv
Скрипт только заполняет пустые значения у записей с совпавшим external_id; остальное не трогает.
"""
import csv
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

DSN = os.environ.get("APPEALS_DSN", "postgresql://appeals:appeals@127.0.0.1:5433/appeals")

path = sys.argv[1]
with open(path, encoding="utf-8-sig", newline="") as f:
    rows = [
        (r["external_id"].strip(), r["problem_id"].strip(), r["subtopic"].strip())
        for r in csv.DictReader(f)
        if r.get("external_id") and r.get("problem_id")
    ]
print(f"Строк с эталоном в файле: {len(rows)}")

conn = psycopg2.connect(DSN)
try:
    with conn, conn.cursor() as cur:
        updated = execute_values(
            cur,
            "UPDATE appeals a SET problem_id = v.pid, subtopic = v.sub "
            "FROM (VALUES %s) AS v(ext, pid, sub) "
            "WHERE a.external_id = v.ext AND a.problem_id IS NULL RETURNING a.id",
            rows,
            page_size=1000,
            fetch=True,
        )
        print(f"Обновлено записей: {len(updated)}")
finally:
    conn.close()
