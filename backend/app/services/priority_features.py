"""Шаг 5.1: компоненты приоритета кластера обращений и итоговая оценка (метод rules_v1).

Приоритет считается для кластера (проблемы), а не для отдельной жалобы.
Пять компонентов в [0, 1]: срочность, значимость, масштаб, возраст, динамика.
score = 100 * сумма(вес * компонент). Расчёт ведётся «на дату» as_of: обращения позже неё не учитываются.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import text as sql

# Уровни срочности 0..3 по ключевым фразам (начальные экспертные правила; уточняются в шагах 5.2-5.3)
URGENCY_3 = re.compile(
    r"открыт\w* люк|без крышки|оголённ|оголенн|обрыв\w* провод|провис\w* провод|на проводах|прорыв|"
    r"затопил|затоплен|нет отоплен|без отоплен|нет воды|без воды|газ\w* утечк|утечк\w* газа|запах газа|"
    r"провал|упал\w* дерев|угрож\w* жизн|искрит|искрят", re.I)
URGENCY_2 = re.compile(r"опасн|авари|заносит|дтп|травм|скользк|гололёд|гололед|без света", re.I)
URGENCY_1 = re.compile(r"яма|ямы|выбоин|не убира|не работает|не горит|мусор|разбит|сломан|не вывозят", re.I)
SOCIAL = re.compile(r"детск\w* сад|детсад|школ|больниц|поликлиник|остановк|пешеходн|перех[оо]д|интернат|роддом", re.I)

COMPONENTS = ("urgency", "significance", "scale", "age", "dynamics")


@dataclass
class PriorityConfig:
    method: str = "rules_v1"
    weights: dict = field(default_factory=lambda: {
        "urgency": 0.35, "significance": 0.20, "scale": 0.25, "age": 0.10, "dynamics": 0.10})
    # начальная значимость категорий (допущение; в categories.base_weight часть значений не настроена)
    category_significance: dict = field(default_factory=lambda: {
        "roads": 0.8, "lighting": 0.6, "transport": 0.7, "other": 0.3,
        "garbage": 0.5, "utilities": 0.9, "landscaping": 0.4})
    default_significance: float = 0.5
    scale_ref: int = 10          # размер кластера, при котором масштаб = 1
    age_ref_days: float = 14.0   # возраст, при котором компонент = 1
    window_days: int = 30        # в снимок попадают кластеры с обращением за последние N суток
    recent_days: int = 7         # окно динамики


DEFAULT_CONFIG = PriorityConfig()


def urgency_level(text: str) -> int:
    if URGENCY_3.search(text):
        return 3
    if URGENCY_2.search(text):
        return 2
    if URGENCY_1.search(text):
        return 1
    return 0


def is_social(text: str) -> bool:
    return bool(SOCIAL.search(text))


def compute_components(appeals, category_code: str, as_of: datetime, cfg: PriorityConfig = DEFAULT_CONFIG):
    """appeals: список пар (text, created_at). Возвращает словарь компонентов и сырых значений или None."""
    members = [(t, c) for t, c in appeals if c <= as_of]
    if not members:
        return None
    n = len(members)
    level = max(urgency_level(t) for t, _ in members)
    social = any(is_social(t) for t, _ in members)
    cat_w = cfg.category_significance.get(category_code, cfg.default_significance)
    first = min(c for _, c in members)
    age_days = (as_of - first).total_seconds() / 86400
    d = timedelta(days=cfg.recent_days)
    recent = sum(1 for _, c in members if as_of - d < c <= as_of)
    prev = sum(1 for _, c in members if as_of - 2 * d < c <= as_of - d)
    comp = {
        "urgency": level / 3,
        "significance": 0.6 * cat_w + 0.4 * (1.0 if social else 0.0),
        "scale": min(1.0, math.log(1 + n) / math.log(1 + cfg.scale_ref)),
        "age": min(1.0, age_days / cfg.age_ref_days),
        "dynamics": recent / (recent + prev + 1),
    }
    raw = {"appeals": n, "urgency_level": level, "social_object": social, "category": category_code,
           "age_days": round(age_days, 1), "recent": recent, "previous": prev}
    return {"components": {k: round(v, 4) for k, v in comp.items()}, "raw": raw}


def score_from_components(comp: dict, cfg: PriorityConfig = DEFAULT_CONFIG) -> float:
    return round(100 * sum(cfg.weights[k] * comp[k] for k in COMPONENTS), 2)


def compute_all(session, as_of: datetime, cfg: PriorityConfig = DEFAULT_CONFIG, save: bool = False):
    """Приоритет всех активных кластеров на дату as_of. Возвращает список по убыванию score."""
    rows = session.execute(sql(
        "SELECT a.cluster_id, a.text, a.created_at, c.code "
        "FROM appeals a JOIN clusters cl ON cl.id = a.cluster_id "
        "JOIN categories c ON c.id = cl.category_id "
        "WHERE a.created_at <= :as_of"), {"as_of": as_of}).fetchall()
    groups, cat = defaultdict(list), {}
    for cid, text, created, code in rows:
        groups[cid].append((text, created))
        cat[cid] = code
    since = as_of - timedelta(days=cfg.window_days)
    out = []
    for cid, items in groups.items():
        if max(c for _, c in items) < since:
            continue
        r = compute_components(items, cat[cid], as_of, cfg)
        if r is None:
            continue
        factors = {**r, "weights": cfg.weights, "as_of": as_of.isoformat(), "method": cfg.method}
        out.append({"cluster_id": cid, "score": score_from_components(r["components"], cfg),
                    "factors": factors, "example": items[0][0][:90]})
    out.sort(key=lambda x: -x["score"])
    if save:
        session.execute(sql("DELETE FROM priority_scores WHERE method = :m AND as_of = :a"),
                        {"m": cfg.method, "a": as_of})
        session.execute(sql(
            "INSERT INTO priority_scores (cluster_id, score, factors, method, as_of) "
            "VALUES (:cid, :score, CAST(:factors AS jsonb), :method, :as_of)"),
            [{"cid": o["cluster_id"], "score": o["score"], "factors": json.dumps(o["factors"], ensure_ascii=False),
              "method": cfg.method, "as_of": as_of} for o in out])
        session.commit()
    return out