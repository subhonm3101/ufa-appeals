"""Шаг 6.3c: недельный прогноз нагрузки (горизонт 4 недели).

Ряды: город, 7 категорий, 7 районов, 49 пар категория x район.
Недели = подряд идущие 7-дневные блоки с первого дня данных (неполный хвост отброшен).
Методы: naive_last (последняя неделя), mean4 (среднее 4 недель), mean8,
sarima (ARMA(1,1) с константой, 80% интервал; только для город/категории/районы).
Оценка: скользящая, начало прогноза каждую неделю, минимум 20 недель обучения.

Запуск из корня проекта:
    python ml\\forecast_weekly.py
"""
import os
import warnings

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from statsmodels.tsa.statespace.sarimax import SARIMAX

from anomalies_zscore import URL

H, MIN_TRAIN = 4, 20
warnings.filterwarnings("ignore")


def load_weekly(engine):
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT a.day, c.code, d.name, a.cnt FROM aggregates_daily a "
            "JOIN categories c ON c.id = a.category_id "
            "JOIN districts d ON d.id = a.district_id"
        )).fetchall()
    df = pd.DataFrame(rows, columns=["day", "cat", "dist", "cnt"])
    df["day"] = pd.to_datetime(df["day"])
    df["week"] = (df["day"] - df["day"].min()).dt.days // 7
    nweeks = int(df["week"].max())  # последняя неделя неполная, отбрасываем
    df = df[df["week"] < nweeks]
    idx = pd.RangeIndex(nweeks)

    def to_dict(keys):
        out = {}
        if keys is None:
            out["ГОРОД"] = df.groupby("week")["cnt"].sum().reindex(idx, fill_value=0).values.astype(float)
            return out
        for k, g in df.groupby(keys):
            name = k if isinstance(k, str) else " / ".join(k)
            out[name] = g.groupby("week")["cnt"].sum().reindex(idx, fill_value=0).values.astype(float)
        return out

    return {
        "город": to_dict(None),
        "категории (7)": to_dict("cat"),
        "районы (7)": to_dict("dist"),
        "категория x район (49)": to_dict(["cat", "dist"]),
    }, nweeks


def f_naive(tr):
    return np.repeat(tr[-1], H), None, None


def f_mean4(tr):
    return np.repeat(tr[-4:].mean(), H), None, None


def f_mean8(tr):
    return np.repeat(tr[-8:].mean(), H), None, None


def f_sarima(tr):
    try:
        res = SARIMAX(tr, order=(1, 0, 1), trend="c",
                      enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
        fc = res.get_forecast(H)
        ci = fc.conf_int(alpha=0.2)
        return np.clip(fc.predicted_mean, 0, None), np.clip(ci[:, 0], 0, None), ci[:, 1]
    except Exception:
        return f_mean4(tr)


def evaluate(series, methods):
    n = len(next(iter(series.values())))
    stats = {m: {"abs": 0.0, "y": 0.0, "mae": [], "cov": [], "cnt": 0} for m in methods}
    for name, s in series.items():
        errs = {m: [] for m in methods}
        for end in range(MIN_TRAIN, n - H + 1):
            tr, y = s[:end], s[end:end + H]
            for m, fn in methods.items():
                p, lo, hi = fn(tr)
                errs[m] += list(np.abs(y - p))
                if lo is not None:
                    stats[m]["cov"] += list((y >= lo) & (y <= hi))
                stats[m]["y"] += float(y.sum())
        for m in methods:
            stats[m]["abs"] += float(np.sum(errs[m]))
            stats[m]["mae"].append(float(np.mean(errs[m])))
    rows = {}
    for m, st in stats.items():
        rows[m] = {
            "WAPE, %": round(100 * st["abs"] / st["y"], 1),
            "MAE, обращений/нед (среднее по рядам)": round(float(np.mean(st["mae"])), 2),
            "покрытие 80%, %": round(100 * float(np.mean(st["cov"])), 1) if st["cov"] else "-",
        }
    return pd.DataFrame(rows).T


def main():
    groups, nweeks = load_weekly(create_engine(URL))
    print(f"Недель: {nweeks}, начал прогноза на ряд: {nweeks - H - MIN_TRAIN + 1}")
    simple = {"naive_last": f_naive, "mean4": f_mean4, "mean8": f_mean8}
    full = dict(simple, sarima=f_sarima)

    parts = []
    for gname, series in groups.items():
        methods = simple if "49" in gname else full
        tab = evaluate(series, methods)
        fmt = tab.to_markdown() if hasattr(tab, "to_markdown") else tab.to_string()
        block = f"{gname}: рядов {len(series)}\n\n{fmt}\n"
        print(block)
        parts.append(block)
    out = "ml/results/e6_forecast_weekly.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("Э6, часть 3: недельный прогноз, горизонт 4 недели, скользящая оценка\n\n")
        f.write("\n".join(parts))
    print("Сохранено:", out)


if __name__ == "__main__":
    main()
