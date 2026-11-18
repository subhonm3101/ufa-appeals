"""Онлайн-кластеризация нового обращения: в какой существующий кластер оно попадает.

Правило (облегчённая версия офлайн-кластеризации, без нейросети):
кандидаты — кластеры того же района, где последнее обращение не старше WINDOW_DAYS;
близость — косинус TF-IDF по символьным n-граммам между текстом обращения и текстами кластера.
"""
from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

WINDOW_DAYS = 30.0
MEMBERS_PER_CLUSTER = 10  # сколько последних текстов кластера сравниваем


def best_match(new_text: str, candidates: dict[int, list[str]]) -> tuple[int | None, float]:
    """Возвращает (id кластера, близость) для самого похожего кластера или (None, 0.0)."""
    owners: list[int] = []
    texts: list[str] = []
    for cid, items in candidates.items():
        for t in items[-MEMBERS_PER_CLUSTER:]:
            owners.append(cid)
            texts.append(t)
    if not texts:
        return None, 0.0
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, lowercase=True)
    try:
        m = vec.fit_transform(texts + [new_text])
    except ValueError:
        return None, 0.0
    sims = (m[:-1] @ m[-1].T).toarray().ravel()
    i = int(np.argmax(sims))
    return owners[i], float(sims[i])


def pick_cluster(new_text: str, candidates: dict[int, list[str]], threshold: float) -> int | None:
    cid, score = best_match(new_text, candidates)
    return cid if cid is not None and score >= threshold else None
