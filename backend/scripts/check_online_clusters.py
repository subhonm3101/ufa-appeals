"""Шаг 14.2: насколько онлайн-правило совпадает с офлайн-кластерами. Запуск из корня проекта:

    python backend/scripts/check_online_clusters.py --limit 3000
"""
import argparse
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sklearn.metrics import pair_confusion_matrix
from sqlalchemy import text

from app.db import SessionLocal
from app.services.online_cluster import WINDOW_DAYS, pick_cluster


def pair_f1(true, pred):
    (tn, fp), (fn, tp) = pair_confusion_matrix(true, pred)
    tp, fp, fn = tp / 2, fp / 2, fn / 2
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def simulate(rows, threshold):
    clusters = {}  # id -> {"district", "last", "texts"}
    pred = []
    next_id = 0
    for _, body, created, district, _ in rows:
        cand = {cid: c["texts"] for cid, c in clusters.items()
                if c["district"] == district and created - c["last"] <= timedelta(days=WINDOW_DAYS)}
        cid = pick_cluster(body, cand, threshold)
        if cid is None:
            cid = next_id
            next_id += 1
            clusters[cid] = {"district": district, "last": created, "texts": []}
        clusters[cid]["texts"].append(body)
        clusters[cid]["last"] = created
        pred.append(cid)
    return pred, len(clusters)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--thresholds", default="0.15,0.25,0.35,0.45")
    a = ap.parse_args()
    with SessionLocal() as s:
        rows = s.execute(text(
            "SELECT id, text, created_at, district_id, cluster_id FROM appeals "
            "WHERE cluster_id IS NOT NULL ORDER BY created_at, id LIMIT :n"), {"n": a.limit}).fetchall()
    true = [r[4] for r in rows]
    print(f"Обращений: {len(rows)}, офлайн-кластеров среди них: {len(set(true))}")
    print("порог   кластеров   precision  recall    F1")
    for t in (float(x) for x in a.thresholds.split(",")):
        pred, n = simulate(rows, t)
        p, r, f = pair_f1(true, pred)
        print(f"{t:5.2f}  {n:9d}   {p:9.3f}  {r:6.3f}  {f:6.3f}")


if __name__ == "__main__":
    main()
