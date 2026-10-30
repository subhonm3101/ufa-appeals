"""Общие метрики эксперимента Э3 (шаги 5.2-5.3): Спирмен, NDCG, бутстреп."""
from __future__ import annotations

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score


def gains(r) -> np.ndarray:
    """Выигрыш для NDCG: оценка 5 весит заметно больше, чем 3."""
    return np.power(2.0, np.asarray(r, float)) - 1


def ndcg(y, s, k: int) -> float:
    return float(ndcg_score([gains(y)], [np.asarray(s, float)], k=k))


def rand_ndcg(y, k: int, rng, n: int = 1000) -> float:
    """Средний NDCG@k при случайном порядке (нижняя планка)."""
    g = gains(y)
    return float(np.mean([ndcg_score([g], [rng.random(len(g))], k=k) for _ in range(n)]))


def safe_rho(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if np.nanstd(x) == 0 or np.nanstd(y) == 0:
        return float("nan")
    return float(spearmanr(x, y)[0])


def boot_rho_ci(s, y, rng, b: int = 2000):
    """Спирмен и 95% доверительный интервал (бутстреп по кластерам)."""
    s, y = np.asarray(s, float), np.asarray(y, float)
    n = len(s)
    boots = [safe_rho(s[i], y[i]) for i in rng.integers(0, n, (b, n))]
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    return safe_rho(s, y), float(lo), float(hi)
