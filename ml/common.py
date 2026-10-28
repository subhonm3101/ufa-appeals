"""Общие функции для экспериментов ML: загрузка данных и честное деление на выборки (шаг 4.1).

Главная идея: обращения с одним problem_id описывают одну и ту же проблему (дубликаты).
Если такие обращения попадут и в обучение, и в тест, метрики будут завышены.
Поэтому деление всегда идёт по группам problem_id.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

REQUIRED = ["external_id", "text", "category", "problem_id", "subtopic"]


def load_dataset(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"В файле нет колонок: {missing}")
    df = df.dropna(subset=["text", "category", "problem_id"]).reset_index(drop=True)
    df["text"] = df["text"].astype(str).str.strip()
    return df[df["text"] != ""].reset_index(drop=True)


def _group_fold(df: pd.DataFrame, idx: np.ndarray, n_splits: int, seed: int):
    """Один фолд StratifiedGroupKFold: (остаток, выделенная часть). Группы не пересекаются."""
    sub = df.iloc[idx]
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    rest, part = next(sgkf.split(sub, sub["category"], groups=sub["problem_id"]))
    return idx[rest], idx[part]


def grouped_split(df: pd.DataFrame, seed: int = 2026) -> dict[str, np.ndarray]:
    """Сценарий A: деление ≈70/15/15 по problem_id, классы распределены пропорционально."""
    all_idx = np.arange(len(df))
    train_val, test = _group_fold(df, all_idx, n_splits=7, seed=seed)   # ≈14% в тест
    train, val = _group_fold(df, train_val, n_splits=6, seed=seed + 1)  # ≈14% в валидацию
    return {"train": train, "val": val, "test": test}


def heldout_subtopic_split(
    df: pd.DataFrame, seed: int = 2026, test_share: float = 0.3
) -> dict[str, np.ndarray]:
    """Сценарий B: ≈30% подтем каждой категории целиком уходят в тест.

    Модель не видела этих формулировок ни разу: проверка обобщения, а не запоминания шаблонов.
    В каждой категории хотя бы одна подтема остаётся в обучении.
    """
    rng = np.random.default_rng(seed)
    held: set[tuple[str, str]] = set()
    for cat, g in df.groupby("category"):
        subs = sorted(g["subtopic"].dropna().unique())
        k = min(max(1, round(len(subs) * test_share)), len(subs) - 1) if len(subs) > 1 else 0
        for s in rng.choice(subs, size=k, replace=False):
            held.add((cat, s))
    is_test = np.array([(c, s) in held for c, s in zip(df["category"], df["subtopic"])])
    test = np.where(is_test)[0]
    rest = np.where(~is_test)[0]
    train, val = _group_fold(df, rest, n_splits=6, seed=seed)  # ≈1/6 остатка в валидацию
    return {"train": train, "val": val, "test": test}


def random_split(df: pd.DataFrame, seed: int = 2026) -> dict[str, np.ndarray]:
    """Сценарий C (только для демонстрации утечки): случайное деление строк, без групп."""
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(df))
    n = len(df)
    n_test, n_val = int(n * 0.15), int(n * 0.15)
    return {"test": perm[:n_test], "val": perm[n_test:n_test + n_val], "train": perm[n_test + n_val:]}


def assert_no_group_leak(df: pd.DataFrame, split: dict[str, np.ndarray]) -> None:
    g = {k: set(df.iloc[v]["problem_id"]) for k, v in split.items()}
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        both = g[a] & g[b]
        if both:
            raise AssertionError(f"Утечка: {len(both)} problem_id есть и в {a}, и в {b}")


def split_summary(df: pd.DataFrame, split: dict[str, np.ndarray]) -> pd.DataFrame:
    """Таблица: размер выборок и число групп/подтем."""
    rows = []
    for name in ("train", "val", "test"):
        part = df.iloc[split[name]]
        rows.append({"выборка": name, "обращений": len(part),
                     "problem_id": part["problem_id"].nunique(),
                     "подтем": part["subtopic"].nunique()})
    return pd.DataFrame(rows)
