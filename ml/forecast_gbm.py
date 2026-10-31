"""Шаг 6.3b: прогноз нагрузки, город и категории; сравнение mean4, SARIMA, бустинг.

Бустинг: HistGradientBoostingRegressor (loss=poisson), одна модель на ряд для всех
горизонтов 1..28. Признаки используют только данные до дня начала прогноза.
Оценка та же, что в 6.3a: начало прогноза каждые 7 дней, горизонт 28, минимум 140 дней.

Запуск из корня проекта:
    python ml\\forecast_gbm.py
"""
import math
import os
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sqlalchemy import create_engine, text
from statsmodels.tsa.statespace.sarimax import SARIMAX

from anomalies_zscore import URL

H, MIN_TRAIN, STEP = 28, 140, 7
warnings.filterwarnings("ignore")


def load_series(engine):
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT a.day, c.code, sum(a.cnt) FROM aggregates_daily a "
            "JOIN categories c ON c.id = a.category_id GROUP BY 1, 2 ORDER BY 1"
        )).fetchall()
    df = pd.DataFrame(rows, columns=["day", "code", "cnt"])
    df["day"] = pd.to_datetime(df["day"])
    wide = df.pivot(index="day", columns="code", values="cnt").fillna(0.0)
    wide = wide.asfreq("D", fill_value=0.0).astype(float)
    series = {"ГОРОД (всего)": wide.sum(axis=1)}
    for code in sorted(wide.columns):
        series[code] = wide[code]
    return series


def f_mean4(train, h):
    prof = train.values[-28:].reshape(4, 7).mean(axis=0)
    return np.tile(prof, int(np.ceil(h / 7)))[:h]


def f_sarima(train, h):
    try:
        res = SARIMAX(train.values, order=(1, 0, 1), seasonal_order=(1, 1, 1, 7),
                      enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
        return np.clip(res.get_forecast(h).predicted_mean, 0, None), False
    except Exception:
        return f_mean4(train, h), True


def build_features(s):
    arr, idx, n = s.values, s.index, len(s)
    X, T, K, Y = [], [], [], []
    for t in range(28, n - 1):
        m7, m28 = arr[t - 6:t + 1].mean(), arr[t - 27:t + 1].mean()
        for k in range(1, H + 1):
            if t + k > n - 1:
                break
            c = math.ceil(k / 7)
            lags = [arr[t + k - 7 * (c + j)] for j in range(4)]
            d = idx[t] + pd.Timedelta(days=k)
            X.append([k, d.dayofweek, d.month, arr[t], m7, m28, lags[0], float(np.mean(lags))])
            T.append(t)
            K.append(k)
            Y.append(arr[t + k])
    return np.array(X), np.array(T), np.array(K), np.array(Y)


def main():
    series = load_series(create_engine(URL))
    names = list(series)
    n = len(series[names[0]])
    origins = list(range(MIN_TRAIN, n - H + 1, STEP))
    print(f"Рядов: {len(names)}, дней: {n}, начал прогноза: {len(origins)}")

    methods = ["mean4_weeks", "sarima", "gbm"]
    res = {}
    fallbacks = 0
    for name in names:
        s = series[name]
        X, T, K, Y = build_features(s)
        acc = {m: [] for m in methods}
        ys = []
        for end in origins:
            train, test = s.iloc[:end], s.iloc[end:end + H].values
            ys += list(test)
            acc["mean4_weeks"] += list(f_mean4(train, H))
            p, fb = f_sarima(train, H)
            fallbacks += int(fb)
            acc["sarima"] += list(p)
            tr = (T + K) <= end - 1
            te = T == end - 1
            model = HistGradientBoostingRegressor(
                loss="poisson", max_depth=3, learning_rate=0.05, max_iter=150,
                min_samples_leaf=20, random_state=0)
            model.fit(X[tr], Y[tr])
            order = np.argsort(K[te])
            acc["gbm"] += list(model.predict(X[te][order]))
        res[name] = (np.array(ys), {m: np.array(v) for m, v in acc.items()})
        print("готово:", name)

    mae, wape = {}, {}
    for name, (y, preds) in res.items():
        mae[name] = {m: np.abs(y - p).mean() for m, p in preds.items()}
        wape[name] = {m: 100 * np.abs(y - p).sum() / y.sum() for m, p in preds.items()}
    cats = [n_ for n_ in names if n_ != names[0]]
    wape["категории (суммарно)"] = {
        m: 100 * sum(np.abs(res[c][0] - res[c][1][m]).sum() for c in cats)
        / sum(res[c][0].sum() for c in cats) for m in methods}
    mae["категории (среднее)"] = {m: np.mean([mae[c][m] for c in cats]) for m in methods}

    t_mae = pd.DataFrame(mae).T.round(2)
    t_wape = pd.DataFrame(wape).T.round(1)
    fmt = lambda d: d.to_markdown() if hasattr(d, "to_markdown") else d.to_string()
    text_out = ("Э6, часть 2: прогноз на 28 дней, скользящая оценка (29 начал прогноза)\n\n"
                "MAE (обращений в день)\n\n" + fmt(t_mae) + "\n\nWAPE, %\n\n" + fmt(t_wape) + "\n")
    print(text_out)
    print("SARIMA откатилась на mean4_weeks:", fallbacks, "раз")
    out = "ml/results/e6_forecast_gbm.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text_out)
    print("Сохранено:", out)


if __name__ == "__main__":
    main()
