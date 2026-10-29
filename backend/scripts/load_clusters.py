"""Шаг 5.1 (часть 2б): загрузка кластеров из CSV в таблицы clusters и appeals.cluster_id.

    python backend/scripts/load_clusters.py data/cluster_assignments.csv --dry-run
    python backend/scripts/load_clusters.py data/cluster_assignments.csv
    python backend/scripts/load_clusters.py data/cluster_assignments.csv --reset   # перезагрузка

Обращения, которых нет в CSV (например TEST-...), остаются без кластера.
--reset очищает только производные таблицы: priority_scores, clusters и appeals.cluster_id.
"""
import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

import psycopg2
from psycopg2.extras import execute_values

DEFAULT_DSN = os.environ.get("APPEALS_DSN", "postgresql://appeals:appeals@127.0.0.1:5433/appeals")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    a = ap.parse_args()

    with open(a.csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    ext_to_key = {r["external_id"]: r["cluster_key"] for r in rows}
    print(f"В CSV: {len(ext_to_key)} обращений, {len(set(ext_to_key.values()))} кластеров")

    conn = psycopg2.connect(a.dsn)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM clusters")
            existing = cur.fetchone()[0]
            if existing and not a.reset:
                sys.exit(f"В clusters уже {existing} строк. Для перезагрузки добавь --reset.")

            cur.execute("SELECT id, external_id, category_id, district_id, lat, lon, created_at "
                        "FROM appeals WHERE external_id = ANY(%s)", (list(ext_to_key),))
            found = cur.fetchall()
            print(f"Найдено в БД: {len(found)} из {len(ext_to_key)}")
            if len(found) != len(ext_to_key):
                sys.exit("Не все external_id из CSV есть в БД. Загрузка отменена.")

            groups = defaultdict(list)
            for r in found:
                groups[ext_to_key[r[1]]].append(r)

            plan = []
            for key, items in groups.items():
                cat = Counter(i[2] for i in items).most_common(1)[0][0]
                dist = Counter(i[3] for i in items).most_common(1)[0][0]
                lat = sum(i[4] for i in items) / len(items)
                lon = sum(i[5] for i in items) / len(items)
                times = [i[6] for i in items]
                plan.append((key, cat, dist, lat, lon, len(items), min(times), max(times), [i[0] for i in items]))
            sizes = sorted(p[5] for p in plan)
            print(f"К загрузке: {len(plan)} кластеров, размер: медиана {sizes[len(sizes) // 2]}, макс {sizes[-1]}")
            if a.dry_run:
                print("--dry-run: в БД ничего не записано")
                conn.rollback()
                return

            if a.reset:
                cur.execute("DELETE FROM priority_scores")
                cur.execute("UPDATE appeals SET cluster_id = NULL")
                cur.execute("DELETE FROM clusters")
                print("Сброшено: priority_scores, clusters, appeals.cluster_id")

            pairs = []
            for key, cat, dist, lat, lon, cnt, first, last, ids in plan:
                cur.execute(
                    "INSERT INTO clusters (category_id, district_id, centroid_lat, centroid_lon, "
                    "appeals_count, first_seen, last_seen, status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,'open') RETURNING id",
                    (cat, dist, lat, lon, cnt, first, last))
                cid = cur.fetchone()[0]
                pairs.extend((i, cid) for i in ids)
            execute_values(cur, "UPDATE appeals a SET cluster_id = v.cid FROM (VALUES %s) AS v(id, cid) "
                                "WHERE a.id = v.id", pairs, template="(%s, %s)", page_size=2000)
            print(f"Записано: {len(plan)} кластеров, обновлено обращений: {len(pairs)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()