"""Шаг 6.2c: какие события детектор считает аномалиями, но в эталоне их нет.

Запуск из корня проекта:
    python ml\\anomalies_false.py
"""
import numpy as np
import pandas as pd
from sqlalchemy import create_engine

from anomalies_zscore import URL, load_daily, detect


def main():
    df = load_daily(create_engine(URL))
    truth = pd.read_csv("data/anomalies_truth.csv", parse_dates=["start_date", "end_date"])
    ev = detect(df, 1e-5, 5)

    def is_true(e):
        t = truth[(truth["category"] == e["category"]) & (truth["district"] == e["district"])
                  & (truth["start_date"] <= e["end"]) & (truth["end_date"] >= e["start"])]
        return len(t) > 0

    ev["верный"] = ev.apply(is_true, axis=1)
    false = ev[~ev["верный"]].copy()
    false["длит, дн"] = (false["end"] - false["start"]).dt.days + 1
    cols = ["category", "district", "start", "end", "длит, дн", "peak", "lam"]
    false["start"] = false["start"].dt.date
    false["end"] = false["end"].dt.date
    false["peak"] = false["peak"].round(0)
    false["lam"] = false["lam"].round(1)
    print(f"Ложных событий: {len(false)} из {len(ev)} найденных")
    print(false[cols].sort_values("start").to_string(index=False))

    print("\nПо категориям:")
    print(false["category"].value_counts().to_string())
    print("\nПо районам:")
    print(false["district"].value_counts().to_string())
    print("\nПо месяцам начала:")
    print(pd.to_datetime(false["start"]).dt.to_period("M").value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
