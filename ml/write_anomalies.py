"""Шаг 6.4a: запись аномалий в таблицу anomalies.

Метод: пуассоновский детектор по числу НОВЫХ кластеров (проблем), окно 7 дней,
норма ряда = медиана 7-дневных сумм (не меньше 0,5), порог p < 1e-3, минимум 3 новых кластера.
Для каждого аномального дня пишется строка: observed = сумма за 7 дней, expected = норма,
score = -log10(p), не более 10. Скрипт можно запускать повторно: таблица пересчитывается целиком.

Запуск из корня проекта:
    python ml\\write_anomalies.py
"""
import numpy as np
import pandas as pd
from scipy.stats import poisson
from sqlalchemy import create_engine, text

from anomalies_zscore import URL

TZ = "Asia/Yekaterinburg"
WINDOW, P_THR, MIN_COUNT = 7, 1e-3, 3


def main():
    engine = create_engine(URL)
    with engine.connect() as conn:
        grid = pd.DataFrame(conn.execute(text(
            "SELECT day, category_id, district_id FROM aggregates_daily")).fetchall(),
            columns=["day", "cat", "dist"])
        nc = pd.DataFrame(conn.execute(text(
            "SELECT (first_seen AT TIME ZONE :tz)::date, category_id, district_id, count(*) "
            "FROM clusters GROUP BY 1, 2, 3"), {"tz": TZ}).fetchall(),
            columns=["day", "cat", "dist", "n"])
        names = {
            "cat": dict(conn.execute(text("SELECT id, code FROM categories")).fetchall()),
            "dist": dict(conn.execute(text("SELECT id, name FROM districts")).fetchall()),
        }
    grid["day"] = pd.to_datetime(grid["day"])
    nc["day"] = pd.to_datetime(nc["day"])
    df = grid.merge(nc, on=["day", "cat", "dist"], how="left")
    df["n"] = df["n"].fillna(0).astype(float)

    rows, events = [], []
    for (cat, dist), g in df.groupby(["cat", "dist"]):
        g = g.sort_values("day")
        roll = g["n"].rolling(WINDOW).sum().values
        lam = max(float(np.median(roll[~np.isnan(roll)])), 0.5)
        pval = poisson.sf(np.nan_to_num(roll, nan=0.0) - 1, lam)
        flag = (pval < P_THR) & (np.nan_to_num(roll, nan=0.0) >= MIN_COUNT)
        days = g["day"].values
        i = 0
        while i < len(days):
            if flag[i]:
                j = i
                while j + 1 < len(days) and flag[j + 1]:
                    j += 1
                for k in range(i, j + 1):
                    rows.append({
                        "c": int(cat), "d": int(dist), "day": pd.Timestamp(days[k]).date(),
                        "obs": int(roll[k]), "exp": float(lam),
                        "score": float(min(-np.log10(max(pval[k], 1e-300)), 10.0)),
                    })
                events.append((names["cat"][cat], names["dist"][dist],
                               pd.Timestamp(days[i]).date(), pd.Timestamp(days[j]).date(),
                               int(np.nanmax(roll[i:j + 1])), round(lam, 1)))
                i = j + 1
            else:
                i += 1

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM anomalies"))
        if rows:
            conn.execute(text(
                "INSERT INTO anomalies (category_id, district_id, day, observed, expected, score) "
                "VALUES (:c, :d, :day, :obs, :exp, :score)"), rows)
    print(f"Записано строк (аномальных дней): {len(rows)}, событий: {len(events)}")
    ev = pd.DataFrame(events, columns=["категория", "район", "с", "по", "пик (нов. кластеров/7 дн)", "норма"])
    print(ev.sort_values("с").to_string(index=False))


if __name__ == "__main__":
    main()
