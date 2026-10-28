"""Проверка, что rubert-tiny2 скачивается и работает (запускать у себя, нужен интернет).

    python ml/check_rubert.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np

from ml.embeddings import DEFAULT_MODEL, encode_texts

texts = ["Во дворе не горят фонари, вечером темно.", "Не работают фонари у дома.",
         "Мусорные баки переполнены, запах на весь двор.", "На дороге огромная яма."]
t0 = time.perf_counter()
e = encode_texts(texts, DEFAULT_MODEL)
print("Модель:", DEFAULT_MODEL, "| форма:", e.shape, f"| {time.perf_counter() - t0:.1f} c (с загрузкой)")
sim = e @ e.T
print("Сходство фонарь/фонарь:", round(float(sim[0, 1]), 3))
print("Сходство фонарь/мусор: ", round(float(sim[0, 2]), 3))
print("Сходство фонарь/яма:   ", round(float(sim[0, 3]), 3))
print("OK" if sim[0, 1] > max(sim[0, 2], sim[0, 3]) else "ВНИМАНИЕ: смысловая близость не подтвердилась")
