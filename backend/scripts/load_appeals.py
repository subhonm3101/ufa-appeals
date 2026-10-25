"""Загрузка обращений из CSV в PostgreSQL (шаг 2.2).

Запуск (из корня проекта ufa-appeals):
    python backend/scripts/load_appeals.py data/appeals_test_100.csv --dry-run
    python backend/scripts/load_appeals.py data/appeals_test_100.csv

Скрипт ничего не удаляет и не изменяет: только добавляет новые записи.
Обращения, чей external_id уже есть в таблице appeals, пропускаются.
"""
import argparse
import csv
import os
import sys
from datetime import datetime

DEFAULT_DSN = os.environ.get(
    "APPEALS_DSN", "postgresql://appeals:appeals@127.0.0.1:5433/appeals"
)

CATEGORIES = {
    "roads": "Дороги",
    "garbage": "Мусор",
    "lighting": "Освещение",
    "transport": "Транспорт",
    "utilities": "ЖКХ",
    "landscaping": "Благоустройство",
    "other": "Прочее",
}

REQUIRED = ["external_id", "text", "created_at", "district", "lat", "lon", "category"]


def read_and_validate(path):
    ok, bad = [], []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"В CSV нет обязательных колонок: {missing}")
        for n, row in enumerate(reader, start=2):  # строка 1 это заголовок
            try:
                ext = row["external_id"].strip()
                text = row["text"].strip()
                district = row["district"].strip()
                cat = row["category"].strip()
                if not ext:
                    raise ValueError("пустой external_id")
                if not text:
                    raise ValueError("пустой текст")
                if not district:
                    raise ValueError("пустой район")
                if cat not in CATEGORIES:
                    raise ValueError(f"неизвестная категория '{cat}'")
                created = datetime.fromisoformat(row["created_at"].strip())
                lat, lon = float(row["lat"]), float(row["lon"])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError("координаты вне диапазона")
                ok.append((ext, text, created, district, lat, lon, cat))
            except Exception as e:  # noqa: BLE001
                bad.append((n, str(e)))
    return ok, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    ap.add_argument("--dry-run", action="store_true", help="только проверить файл, в базу не писать")
    args = ap.parse_args()

    ok, bad = read_and_validate(args.csv_path)
    print(f"Файл: {args.csv_path}")
    print(f"Корректных строк: {len(ok)}, с ошибками: {len(bad)}")
    for n, reason in bad[:20]:
        print(f"  строка {n}: {reason}")
    if args.dry_run:
        print("Режим dry-run: в базу ничего не записано.")
        return

    import psycopg2
    from psycopg2.extras import execute_values

    conn = psycopg2.connect(args.dsn)
    try:
        with conn:  # одна транзакция: при ошибке всё откатится
            with conn.cursor() as cur:
                for code, name in CATEGORIES.items():
                    cur.execute(
                        "INSERT INTO categories (code, name_ru) VALUES (%s, %s) "
                        "ON CONFLICT (code) DO NOTHING",
                        (code, name),
                    )
                for d in sorted({r[3] for r in ok}):
                    cur.execute(
                        "INSERT INTO districts (name) "
                        "SELECT %s WHERE NOT EXISTS (SELECT 1 FROM districts WHERE name = %s)",
                        (d, d),
                    )
                cur.execute("SELECT code, id FROM categories")
                cat_id = dict(cur.fetchall())
                cur.execute("SELECT name, MIN(id) FROM districts GROUP BY name")
                dist_id = dict(cur.fetchall())

                cur.execute(
                    "SELECT external_id FROM appeals WHERE external_id = ANY(%s)",
                    ([r[0] for r in ok],),
                )
                existing = {x[0] for x in cur.fetchall()}
                new_rows = [r for r in ok if r[0] not in existing]
                print(f"Уже есть в базе (пропущено): {len(existing)}; будет добавлено: {len(new_rows)}")

                if not new_rows:
                    print("Новых записей нет, партия импорта не создаётся.")
                    return

                cur.execute(
                    "INSERT INTO import_batches (filename, source, rows_total, rows_ok, rows_failed) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (os.path.basename(args.csv_path), "synthetic",
                     len(ok) + len(bad), len(new_rows), len(bad)),
                )
                batch_id = cur.fetchone()[0]

                if new_rows:
                    execute_values(
                        cur,
                        "INSERT INTO appeals "
                        "(batch_id, external_id, text, created_at, district_id, lat, lon, category_id) "
                        "VALUES %s",
                        [(batch_id, r[0], r[1], r[2], dist_id[r[3]], r[4], r[5], cat_id[r[6]])
                         for r in new_rows],
                    )
                print(f"Готово. Партия импорта №{batch_id}, добавлено записей: {len(new_rows)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
