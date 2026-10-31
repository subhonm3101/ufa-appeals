"""Шаг 6.2d: аномалии по новым проблемам (кластерам), а не по обращениям.

Для каждого дня, категории и района считаем, сколько НОВЫХ кластеров появилось
(по дате первого обращения кластера). Дубликаты одной проблемы повторно не считаются.
Дальше тот же пуассоновский детектор и та же оценка по anomalies_truth.csv.

Запуск из корня проекта:
    python ml\\anomalies_clusters.py
"""
import os

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from anomalies_zscore import URL, load_daily, detect

TZ = "Asia/Yekaterinburg"


def load_new_clusters(engine) -> pd.DataFrame:
    q = text(
        "SELECT (k.first_seen AT TIME ZONE :tz)::date AS day, c.code, d.name, count(*) "
        "FROM clusters k JOIN categories c ON c.id = k.category_id "
        "JOIN districts d ON d.id = k.district_id GROUP BY 1, 2, 3"
    )
    with engine.connect() as conn:
        rows = conn.execute(q, {"tz": TZ}).fetchall()
    out = pd.DataFrame(rows, columns=["day", "category", "district", "new_clusters"])
    out["day"] = pd.to_datetime(out["day"])
    return out


def evaluate(ev, truth):
    found, delays, matched = 0, [], set()
    for _, t in truth.iterrows():
        hit = ev.iloc[0:0] if len(ev) == 0 else ev[
            (ev["category"] == t["category"]) & (ev["district"] == t["district"])
            & (ev["start"] <= t["end_date"]) & (ev["end"] >= t["start_date"])]
        if len(hit):
            found += 1
            matched.update(hit.index.tolist())
            delays.append((hit["first_flag"].min() - t["start_date"]).days)
    return found, len(ev) - len(matched), delays


def main():
    engine = create_engine(URL)
    grid = load_daily(engine)[["day", "category", "district"]]
    nc = load_new_clusters(engine)
    df = grid.merge(nc, on=["day", "category", "district"], how="left")
    df["cnt"] = df["new_clusters"].fillna(0).astype(int)
    print(f"Новых кластеров всего: {int(df['cnt'].sum())}")

    truth = pd.read_csv("data/anomalies_truth.csv", parse_dates=["start_date", "end_date"])
    rows = []
    for p_thr in (1e-2, 1e-3, 1e-4, 1e-5):
        ev = detect(df, p_thr, 3)
        found, false_ev, delays = evaluate(ev, truth)
        rows.append({
            "p": f"{p_thr:g}", "min_count": 3,
            "найдено": f"{found} из {len(truth)}", "ложных событий": false_ev,
            "задержка, дн": round(float(np.mean(delays)), 1) if delays else "-",
        })
    res = pd.DataFrame(rows)
    table = res.to_markdown(index=False) if hasattr(res, "to_markdown") else res.to_string(index=False)
    print(table)
    out = "ml/results/e4_anomalies_clusters.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("Э4, часть 3: пуассоновский детектор по новым кластерам (окно 7 дней)\n\n" + table + "\n")
    print("Сохранено:", out)


if __name__ == "__main__":
    main()
