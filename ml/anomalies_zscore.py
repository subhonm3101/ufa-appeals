"""Шаг 6.2a: детектор аномалий (всплесков) по рядам категория x район.

Идея: для каждого ряда считаем число обращений за скользящие 7 дней.
Норма ряда = медиана этих сумм (устойчива к самим всплескам).
Окно считается аномальным, если вероятность увидеть столько обращений
при пуассоновской норме меньше порога p и обращений не меньше min_count.
Подряд идущие аномальные дни склеиваются в события.
Оценка: событие верно найдено, если пересекается с заложенным
в anomalies_truth.csv для той же категории и района.

Запуск из корня проекта:
    python ml\\anomalies_zscore.py
"""
import argparse
import os

import numpy as np
import pandas as pd
from scipy.stats import poisson
from sqlalchemy import create_engine, text

URL = os.environ.get(
    "APPEALS_DATABASE_URL",
    "postgresql+psycopg2://appeals:appeals@127.0.0.1:5433/appeals",
)
WINDOW = 7


def load_daily(engine) -> pd.DataFrame:
    q = text(
        "SELECT a.day, c.code AS category, d.name AS district, a.cnt "
        "FROM aggregates_daily a "
        "JOIN categories c ON c.id = a.category_id "
        "JOIN districts d ON d.id = a.district_id"
    )
    with engine.connect() as conn:
        rows = conn.execute(q).fetchall()
    df = pd.DataFrame(rows, columns=["day", "category", "district", "cnt"])
    df["day"] = pd.to_datetime(df["day"])
    return df


def detect(df: pd.DataFrame, p_thr: float, min_count: int) -> pd.DataFrame:
    """Возвращает события: category, district, first_flag, last_flag, start, end, peak."""
    events = []
    for (cat, dist), g in df.groupby(["category", "district"]):
        s = g.sort_values("day").set_index("day")["cnt"].astype(float)
        roll = s.rolling(WINDOW).sum()
        lam = max(float(np.median(roll.dropna())), 0.5)
        pval = poisson.sf(roll.values - 1, lam)  # P(X >= k)
        flag = (pval < p_thr) & (roll.values >= min_count)
        days = s.index
        i, n = 0, len(days)
        while i < n:
            if flag[i]:
                j = i
                while j + 1 < n and flag[j + 1]:
                    j += 1
                events.append({
                    "category": cat, "district": dist,
                    "first_flag": days[i], "last_flag": days[j],
                    "start": days[i] - pd.Timedelta(days=WINDOW - 1),
                    "end": days[j],
                    "peak": float(np.nanmax(roll.values[i:j + 1])),
                    "lam": lam,
                })
                i = j + 1
            else:
                i += 1
    return pd.DataFrame(events)


def evaluate(ev: pd.DataFrame, truth: pd.DataFrame):
    found, delays, matched_events = 0, [], set()
    for _, t in truth.iterrows():
        hit = ev[(ev["category"] == t["category"]) & (ev["district"] == t["district"])
                 & (ev["start"] <= t["end_date"]) & (ev["end"] >= t["start_date"])] \
            if len(ev) else ev
        if len(hit):
            found += 1
            matched_events.update(hit.index.tolist())
            delays.append((hit["first_flag"].min() - t["start_date"]).days)
    false_events = len(ev) - len(matched_events)
    return found, false_events, delays


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", default="data/anomalies_truth.csv")
    ap.add_argument("--out", default="ml/results/e4_anomalies_zscore.md")
    args = ap.parse_args()

    engine = create_engine(URL)
    df = load_daily(engine)
    truth = pd.read_csv(args.truth, parse_dates=["start_date", "end_date"])

    n_series = df.groupby(["category", "district"]).ngroups
    print(f"Рядов: {n_series}, дней: {df['day'].nunique()}, заложено аномалий: {len(truth)}")

    rows = []
    for p_thr in (1e-2, 1e-3, 1e-4, 1e-5):
        for min_count in (3, 5):
            ev = detect(df, p_thr, min_count)
            found, false_ev, delays = evaluate(ev, truth)
            rows.append({
                "p": f"{p_thr:g}", "min_count": min_count,
                "найдено": f"{found} из {len(truth)}",
                "ложных событий": false_ev,
                "средняя задержка, дн": (round(float(np.mean(delays)), 1) if delays else "-"),
            })
    res = pd.DataFrame(rows)
    table = res.to_markdown(index=False) if hasattr(res, "to_markdown") else res.to_string(index=False)
    print(table)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("Э4, часть 1: пуассоновский детектор (окно 7 дней), уровень категория x район\n\n")
        f.write(table + "\n")
    print("Сохранено:", args.out)


if __name__ == "__main__":
    main()
