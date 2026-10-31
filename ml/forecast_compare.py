"""Шаг 6.3a: прогноз нагрузки, городской ряд (обращений в день).

Методы:
  naive_week      значения прошлой недели повторяются (сезонный наив)
  mean4_weeks     среднее по дням недели за последние 4 недели
  level_28        среднее за последние 28 дней без учёта дня недели (контроль)
  sarima          SARIMAX(1,0,1)(1,1,1,7) с 80% интервалом
Оценка: скользящее начало прогноза каждые 7 дней, горизонт 28 дней,
минимум 140 дней в обучении. Метрики: MAE и WAPE (сумма |ошибок| / сумма фактов).

Запуск из корня проекта:
    python ml\\forecast_compare.py
"""
import os
import warnings

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from statsmodels.tsa.statespace.sarimax import SARIMAX

from anomalies_zscore import URL

H = 28
MIN_TRAIN = 140
STEP = 7
warnings.filterwarnings("ignore")


def load_city(engine) -> pd.Series:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT day, sum(cnt) FROM aggregates_daily GROUP BY day ORDER BY day")
        ).fetchall()
    s = pd.Series({pd.Timestamp(d): float(c) for d, c in rows})
    return s.asfreq("D", fill_value=0.0)


def f_naive_week(train, h):
    return np.tile(train.values[-7:], int(np.ceil(h / 7)))[:h], None, None


def f_mean4(train, h):
    prof = train.values[-28:].reshape(4, 7).mean(axis=0)
    return np.tile(prof, int(np.ceil(h / 7)))[:h], None, None


def f_level(train, h):
    return np.full(h, train.values[-28:].mean()), None, None


def f_sarima(train, h):
    res = SARIMAX(train.values, order=(1, 0, 1), seasonal_order=(1, 1, 1, 7),
                  enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
    fc = res.get_forecast(h)
    ci = fc.conf_int(alpha=0.2)
    return np.clip(fc.predicted_mean, 0, None), np.clip(ci[:, 0], 0, None), ci[:, 1]


METHODS = {
    "level_28 (без дня недели)": f_level,
    "naive_week": f_naive_week,
    "mean4_weeks": f_mean4,
    "sarima": f_sarima,
}


def main():
    s = load_city(create_engine(URL))
    n = len(s)
    print(f"Ряд: {s.index[0].date()} .. {s.index[-1].date()}, дней {n}, "
          f"среднее {s.mean():.1f}, начал прогноза {len(range(MIN_TRAIN, n - H + 1, STEP))}")

    acc = {m: {"y": [], "p": [], "h": [], "lo": [], "hi": []} for m in METHODS}
    for end in range(MIN_TRAIN, n - H + 1, STEP):
        train, test = s.iloc[:end], s.iloc[end:end + H].values
        for name, fn in METHODS.items():
            p, lo, hi = fn(train, H)
            a = acc[name]
            a["y"] += list(test)
            a["p"] += list(p)
            a["h"] += list(range(1, H + 1))
            if lo is not None:
                a["lo"] += list(lo)
                a["hi"] += list(hi)

    rows = []
    for name, a in acc.items():
        y, p, h = map(np.array, (a["y"], a["p"], a["h"]))
        err = np.abs(y - p)
        row = {
            "метод": name,
            "MAE": round(err.mean(), 2),
            "WAPE, %": round(100 * err.sum() / y.sum(), 1),
            "MAE, дни 1-14": round(err[h <= 14].mean(), 2),
            "MAE, дни 15-28": round(err[h > 14].mean(), 2),
        }
        if a["lo"]:
            lo, hi = np.array(a["lo"]), np.array(a["hi"])
            row["покрытие 80%, %"] = round(100 * np.mean((y >= lo) & (y <= hi)), 1)
        else:
            row["покрытие 80%, %"] = "-"
        rows.append(row)

    res = pd.DataFrame(rows)
    table = res.to_markdown(index=False) if hasattr(res, "to_markdown") else res.to_string(index=False)
    print(table)
    out = "ml/results/e6_forecast_baselines.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("Э6, часть 1: прогноз городской нагрузки (горизонт 28 дней, скользящая оценка)\n\n")
        f.write(table + "\n")
    print("Сохранено:", out)


if __name__ == "__main__":
    main()
