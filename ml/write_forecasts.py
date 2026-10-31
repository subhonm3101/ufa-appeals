"""Шаг 6.3d: запись прогнозов в таблицу forecasts и регистрация моделей в ml_models.

Дневной прогноз:   город и 7 категорий, 28 дней, SARIMA(1,0,1)(1,1,1,7).
Недельный прогноз: город, 7 категорий, 7 районов, 4 недели, ARMA(1,1) с константой.
Интервал 80%. Скрипт можно запускать повторно: прежние прогнозы этих моделей заменяются.
Прогноз начинается со дня, следующего за последним днём в aggregates_daily.

Запуск из корня проекта (после alembic upgrade head, ревизия 0006):
    python ml\\write_forecasts.py
"""
import json
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from statsmodels.tsa.statespace.sarimax import SARIMAX

from anomalies_zscore import URL

HD, HW = 28, 4
VERSION = "e6-2026-10-31"
warnings.filterwarnings("ignore")

METRICS_DAILY = {
    "horizon_days": HD, "interval": "80%",
    "eval": "rolling origin, 29 starts, min train 140 days",
    "city_mae": 3.22, "city_wape_pct": 22.3, "city_coverage80_pct": 84.4,
    "categories_wape_pct": 62.8,
}
METRICS_WEEKLY = {
    "horizon_weeks": HW, "interval": "80%",
    "eval": "rolling origin, 29 starts, min train 20 weeks",
    "city_wape_pct": 10.4, "city_coverage80_pct": 78.4,
    "districts_wape_pct": 25.6, "categories_wape_pct": 33.5,
    "note": "for categories mean4 is not worse (32.2%)",
}


def load(engine):
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT day, category_id, district_id, cnt FROM aggregates_daily")).fetchall()
    df = pd.DataFrame(rows, columns=["day", "cat", "dist", "cnt"])
    df["day"] = pd.to_datetime(df["day"])
    return df


def sarima_fc(values, h, order, seasonal=(0, 0, 0, 0), trend=None):
    res = SARIMAX(values, order=order, seasonal_order=seasonal, trend=trend,
                  enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
    fc = res.get_forecast(h)
    ci = fc.conf_int(alpha=0.2)
    return (np.clip(fc.predicted_mean, 0, None), np.clip(ci[:, 0], 0, None),
            np.clip(ci[:, 1], 0, None))


def upsert_model(conn, name, task, metrics):
    row = conn.execute(text("SELECT id FROM ml_models WHERE name=:n AND version=:v"),
                       {"n": name, "v": VERSION}).first()
    params = {"n": name, "t": task, "v": VERSION,
              "m": json.dumps(metrics, ensure_ascii=False),
              "ts": datetime.now(timezone.utc)}
    if row:
        conn.execute(text("UPDATE ml_models SET metrics=CAST(:m AS jsonb), trained_at=:ts "
                          "WHERE id=:id"), dict(params, id=row[0]))
        return row[0]
    return conn.execute(text(
        "INSERT INTO ml_models (task, name, version, metrics, trained_at) "
        "VALUES (:t, :n, :v, CAST(:m AS jsonb), :ts) RETURNING id"), params).scalar_one()


def main():
    engine = create_engine(URL)
    df = load(engine)
    d0, d1 = df["day"].min(), df["day"].max()
    ndays = (d1 - d0).days + 1
    print(f"Данные: {d0.date()} .. {d1.date()} ({ndays} дней)")

    def daily(keycol=None):
        if keycol is None:
            return {None: df.groupby("day")["cnt"].sum().reindex(
                pd.date_range(d0, d1), fill_value=0).values.astype(float)}
        return {int(k): g.groupby("day")["cnt"].sum().reindex(
            pd.date_range(d0, d1), fill_value=0).values.astype(float)
            for k, g in df.groupby(keycol)}

    df["week"] = (df["day"] - d0).dt.days // 7
    nweeks = int(df["week"].max())  # неполная последняя неделя отбрасывается
    dw = df[df["week"] < nweeks]

    def weekly(keycol=None):
        idx = pd.RangeIndex(nweeks)
        if keycol is None:
            return {None: dw.groupby("week")["cnt"].sum().reindex(idx, fill_value=0).values.astype(float)}
        return {int(k): g.groupby("week")["cnt"].sum().reindex(idx, fill_value=0).values.astype(float)
                for k, g in dw.groupby(keycol)}

    out_daily, out_weekly = [], []
    day_targets = [(d1 + pd.Timedelta(days=i + 1)).date() for i in range(HD)]
    week_targets = [(d0 + pd.Timedelta(days=7 * (nweeks + i))).date() for i in range(HW)]

    for key, y in daily().items():
        p, lo, hi = sarima_fc(y, HD, (1, 0, 1), (1, 1, 1, 7))
        out_daily += [(None, None, t, a, b, c) for t, a, b, c in zip(day_targets, p, lo, hi)]
    for key, y in daily("cat").items():
        p, lo, hi = sarima_fc(y, HD, (1, 0, 1), (1, 1, 1, 7))
        out_daily += [(key, None, t, a, b, c) for t, a, b, c in zip(day_targets, p, lo, hi)]

    for key, y in weekly().items():
        p, lo, hi = sarima_fc(y, HW, (1, 0, 1), trend="c")
        out_weekly += [(None, None, t, a, b, c) for t, a, b, c in zip(week_targets, p, lo, hi)]
    for key, y in weekly("cat").items():
        p, lo, hi = sarima_fc(y, HW, (1, 0, 1), trend="c")
        out_weekly += [(key, None, t, a, b, c) for t, a, b, c in zip(week_targets, p, lo, hi)]
    for key, y in weekly("dist").items():
        p, lo, hi = sarima_fc(y, HW, (1, 0, 1), trend="c")
        out_weekly += [(None, key, t, a, b, c) for t, a, b, c in zip(week_targets, p, lo, hi)]

    ins = text(
        "INSERT INTO forecasts (model_id, category_id, district_id, target_date, value, lower, "
        "upper, granularity) VALUES (:m, :c, :d, :t, :v, :lo, :hi, :g)")
    with engine.begin() as conn:
        mid_d = upsert_model(conn, "sarima_daily", "forecast", METRICS_DAILY)
        mid_w = upsert_model(conn, "arma_weekly", "forecast", METRICS_WEEKLY)
        conn.execute(text("DELETE FROM forecasts WHERE model_id IN (:a, :b)"), {"a": mid_d, "b": mid_w})
        for mid, g, rows in ((mid_d, "day", out_daily), (mid_w, "week", out_weekly)):
            conn.execute(ins, [{"m": mid, "c": c, "d": d, "t": t, "v": float(v),
                                "lo": float(lo), "hi": float(hi), "g": g}
                               for c, d, t, v, lo, hi in rows])
        summary = conn.execute(text(
            "SELECT granularity, count(*), min(target_date), max(target_date) "
            "FROM forecasts GROUP BY 1 ORDER BY 1")).fetchall()
        city_week = conn.execute(text(
            "SELECT target_date, round(value::numeric,1), round(lower::numeric,1), "
            "round(upper::numeric,1) FROM forecasts WHERE granularity='week' "
            "AND category_id IS NULL AND district_id IS NULL ORDER BY target_date")).fetchall()
    print(f"Модели: sarima_daily id={mid_d}, arma_weekly id={mid_w}")
    for row in summary:
        print("Записано:", row)
    print("Город, неделя (прогноз, нижняя, верхняя границы):")
    for row in city_week:
        print("  ", row)


if __name__ == "__main__":
    main()
