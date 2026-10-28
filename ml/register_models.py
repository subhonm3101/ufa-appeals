"""Запись метрик Э1 в таблицу ml_models (шаг 4.3b).

Запуск из корня проекта (база должна быть запущена):
    python ml/register_models.py --results ml/results
Повторный запуск не создаёт дубликатов: запись с тем же name и version обновляется.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date

DEFAULT_DSN = os.environ.get("APPEALS_DSN", "postgresql://appeals:appeals@127.0.0.1:5433/appeals")


def upsert_model(cur, task: str, name: str, version: str, metrics: dict) -> tuple[int, bool]:
    """Возвращает (id, создана ли новая запись)."""
    payload = json.dumps(metrics, ensure_ascii=False)
    cur.execute("SELECT id FROM ml_models WHERE task = %s AND name = %s AND version = %s", (task, name, version))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE ml_models SET metrics = %s::jsonb, trained_at = now() WHERE id = %s", (payload, row[0]))
        return row[0], False
    cur.execute(
        "INSERT INTO ml_models (task, name, version, metrics, trained_at) "
        "VALUES (%s, %s, %s, %s::jsonb, now()) RETURNING id", (task, name, version, payload))
    return cur.fetchone()[0], True


def build_metrics(single: dict, multiseed: dict | None, model_key: str) -> dict:
    """single: json одного запуска (по сценариям); multiseed: e1_multiseed.json или None."""
    m = {"experiment": "E1", "single_run": {
        k: {"accuracy": v["test"]["accuracy"], "macro_f1": v["test"]["macro_f1"],
            "best_C": v["best_C"]} for k, v in single.items()}}
    if multiseed:
        m["multiseed"] = {"seeds": multiseed["seeds"], "versions": multiseed["versions"],
                          "macro_f1_mean_std": {k: multiseed["summary"][k][model_key]["macro_f1"]
                                                for k in multiseed["summary"]}}
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="ml/results")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    ap.add_argument("--version", default=f"e1-{date.today().isoformat()}")
    a = ap.parse_args()

    def load(name):
        p = os.path.join(a.results, name)
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None

    tfidf, rubert, multi = load("e1_tfidf_baseline.json"), load("e1_embedding_rubert.json"), load("e1_multiseed.json")
    if not tfidf or not rubert:
        raise SystemExit("Не найдены e1_tfidf_baseline.json и e1_embedding_rubert.json: сначала шаги 4.1 и 4.2")

    import psycopg2
    conn = psycopg2.connect(a.dsn)
    try:
        with conn, conn.cursor() as cur:
            for name, single, key in (("tfidf_logreg", tfidf, "tfidf"), ("rubert_tiny2_logreg", rubert, "rubert")):
                mid, created = upsert_model(cur, "classifier", name, a.version, build_metrics(single, multi, key))
                print(f"{'Создана' if created else 'Обновлена'} запись ml_models id={mid}: {name}, версия {a.version}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
