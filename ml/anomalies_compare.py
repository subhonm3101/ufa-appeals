"""Шаг 6.2b: сравнение детекторов аномалий (Э4, часть 2).

Методы (уровень категория x район, если не указано иное):
  B  устойчивый z-score окна 7 дней (норма = медиана, разброс = max(sqrt(норма), MAD))
  C  Isolation Forest на z-признаках окон 3, 7 и 14 дней
  A2 STL (период 7) + z-score остатков, уровень КАТЕГОРИИ (район не определяется)
Пуассоновский детектор из 6.2a (метод A) берётся из anomalies_zscore.py.

Запуск из корня проекта:
    python ml\\anomalies_compare.py
Нужны: pandas, numpy, scipy, scikit-learn, statsmodels (pip install statsmodels).
"""
import argparse
import os

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from anomalies_zscore import URL, load_daily, detect as detect_poisson
from sqlalchemy import create_engine

try:
    from statsmodels.tsa.seasonal import STL
except ImportError:  # statsmodels может быть не установлен
    STL = None


def robust_z(vals, w):
    roll = pd.Series(vals, dtype=float).rolling(w).sum().values
    valid = roll[~np.isnan(roll)]
    med = float(np.median(valid))
    lam = max(med, 0.3)
    mad = 1.4826 * float(np.median(np.abs(valid - med)))
    sigma = max(np.sqrt(lam), mad, 1.0)
    return roll, (roll - lam) / sigma


def events_from_flags(cat, dist, days, flag, w, roll=None):
    out, i, n = [], 0, len(days)
    while i < n:
        if flag[i]:
            j = i
            while j + 1 < n and flag[j + 1]:
                j += 1
            out.append({
                "category": cat, "district": dist,
                "first_flag": days[i], "last_flag": days[j],
                "start": days[i] - pd.Timedelta(days=w - 1), "end": days[j],
            })
            i = j + 1
        else:
            i += 1
    return out


def detect_z(df, thr, min_count=5, w=7):
    ev = []
    for (cat, dist), g in df.groupby(["category", "district"]):
        g = g.sort_values("day")
        roll, z = robust_z(g["cnt"].values, w)
        flag = (np.nan_to_num(z, nan=-9) > thr) & (np.nan_to_num(roll, nan=0) >= min_count)
        ev += events_from_flags(cat, dist, g["day"].values, flag, w)
    return pd.DataFrame(ev)


def detect_iforest(df, contamination, min_count=5):
    keys, feats, rolls, days_all = [], [], [], []
    for (cat, dist), g in df.groupby(["category", "district"]):
        g = g.sort_values("day")
        v = g["cnt"].values
        r3, z3 = robust_z(v, 3)
        r7, z7 = robust_z(v, 7)
        r14, z14 = robust_z(v, 14)
        X = np.nan_to_num(np.column_stack([z3, z7, z14]), nan=0.0)
        feats.append(X)
        rolls.append(np.nan_to_num(r7, nan=0.0))
        keys += [(cat, dist, len(g))]
        days_all.append(g["day"].values)
    X = np.vstack(feats)
    model = IsolationForest(n_estimators=200, contamination=contamination, random_state=0)
    pred = model.fit_predict(X) == -1
    ev, pos = [], 0
    for (cat, dist, n), roll, days, Xs in zip(keys, rolls, days_all, feats):
        flag = pred[pos:pos + n] & (Xs[:, 1] > 0) & (roll >= min_count)
        ev += events_from_flags(cat, dist, days, flag, 7)
        pos += n
    return pd.DataFrame(ev)


def detect_stl_category(df, thr):
    if STL is None:
        return None
    cat_day = df.groupby(["category", "day"])["cnt"].sum().reset_index()
    ev = []
    for cat, g in cat_day.groupby("category"):
        g = g.sort_values("day")
        res = STL(g["cnt"].astype(float).values, period=7, robust=True).fit().resid
        med = np.median(res)
        mad = 1.4826 * np.median(np.abs(res - med)) or 1.0
        flag = (res - med) / mad > thr
        ev += events_from_flags(cat, None, g["day"].values, flag, 1)
    return pd.DataFrame(ev)


def evaluate(ev, truth, use_district=True):
    found, delays, matched, missed = 0, [], set(), []
    for _, t in truth.iterrows():
        hit = ev.iloc[0:0] if (ev is None or len(ev) == 0) else ev[
            (ev["category"] == t["category"])
            & (ev["start"] <= t["end_date"]) & (ev["end"] >= t["start_date"])]
        if use_district and len(hit):
            hit = hit[hit["district"] == t["district"]]
        if len(hit):
            found += 1
            matched.update(hit.index.tolist())
            delays.append((hit["first_flag"].min() - t["start_date"]).days)
        else:
            missed.append(f"{t['category']}/{t['district']}")
    false_ev = (0 if ev is None else len(ev)) - len(matched)
    return found, false_ev, delays, missed


def row(method, param, ev, truth, use_district=True):
    found, false_ev, delays, missed = evaluate(ev, truth, use_district)
    return {
        "метод": method, "параметр": param,
        "найдено": f"{found} из {len(truth)}", "ложных событий": false_ev,
        "задержка, дн": round(float(np.mean(delays)), 1) if delays else "-",
        "пропущены": ", ".join(missed) if missed else "-",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", default="data/anomalies_truth.csv")
    ap.add_argument("--out", default="ml/results/e4_anomalies_compare.md")
    args = ap.parse_args()

    df = load_daily(create_engine(URL))
    truth = pd.read_csv(args.truth, parse_dates=["start_date", "end_date"])
    rows = []

    ev = detect_poisson(df, 1e-5, 5)
    rows.append(row("A Пуассон (6.2a)", "p=1e-5", ev, truth))
    for thr in (3, 4, 5, 6, 8):
        rows.append(row("B устойчивый z-score", f"z>{thr}", detect_z(df, thr), truth))
    for c in (0.002, 0.005, 0.01):
        rows.append(row("C Isolation Forest", f"contamination={c}", detect_iforest(df, c), truth))
    if STL is None:
        print("statsmodels не установлен: A2 пропущен (pip install statsmodels)")
    else:
        for thr in (3, 4, 5):
            rows.append(row("A2 STL + z, уровень категории", f"z>{thr}",
                            detect_stl_category(df, thr), truth, use_district=False))

    res = pd.DataFrame(rows)
    table = res.to_markdown(index=False) if hasattr(res, "to_markdown") else res.to_string(index=False)
    print(table)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("Э4, часть 2: сравнение детекторов аномалий\n\n" + table + "\n")
    print("Сохранено:", args.out)


if __name__ == "__main__":
    main()
