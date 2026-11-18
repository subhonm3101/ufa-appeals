"""Конвейер нового обращения: кластер, счётчики и приоритет.

Новое обращение сразу получает собственный кластер и строку в priority_scores (метод rules_v1),
поэтому появляется в очереди и на карте. Склейка дубликатов в общие кластеры выполняется
офлайн-кластеризацией (ml/export_clusters.py + backend/scripts/load_clusters.py).
"""
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from .priority_features import DEFAULT_CONFIG, compute_components, score_from_components


def on_new_appeal(session: Session, appeal_id: int) -> int | None:
    """Создаёт кластер для обращения без кластера и считает приоритет. Транзакцию не фиксирует."""
    row = session.execute(
        text("SELECT cluster_id, category_id, district_id, lat, lon, created_at FROM appeals WHERE id = :i"),
        {"i": appeal_id},
    ).first()
    if row is None:
        return None
    cid = row.cluster_id
    if cid is None:
        cid = session.execute(
            text(
                "INSERT INTO clusters (category_id, district_id, centroid_lat, centroid_lon, "
                "appeals_count, first_seen, last_seen, status) "
                "VALUES (:cat, :d, :lat, :lon, 1, :t, :t, 'open') RETURNING id"
            ),
            {"cat": row.category_id, "d": row.district_id, "lat": row.lat, "lon": row.lon, "t": row.created_at},
        ).scalar_one()
        session.execute(text("UPDATE appeals SET cluster_id = :c WHERE id = :i"), {"c": cid, "i": appeal_id})
    refresh_priority(session, cid)
    return cid


def refresh_priority(session: Session, cluster_id: int, cfg=DEFAULT_CONFIG) -> float | None:
    """Пересчитывает приоритет кластера на текущий момент (по часам БД); остаётся одна строка метода."""
    as_of = session.execute(text("SELECT now()")).scalar_one()
    rows = session.execute(
        text("SELECT text, created_at FROM appeals WHERE cluster_id = :c"), {"c": cluster_id}
    ).fetchall()
    if not rows:
        return None
    code = session.execute(
        text("SELECT c.code FROM clusters cl LEFT JOIN categories c ON c.id = cl.category_id WHERE cl.id = :c"),
        {"c": cluster_id},
    ).scalar()
    res = compute_components([(r.text, r.created_at) for r in rows], code or "other", as_of, cfg)
    if res is None:
        return None
    score = score_from_components(res["components"], cfg)
    factors = {**res, "weights": cfg.weights, "as_of": as_of.isoformat(), "method": cfg.method}
    session.execute(
        text("DELETE FROM priority_scores WHERE cluster_id = :c AND method = :m"),
        {"c": cluster_id, "m": cfg.method},
    )
    session.execute(
        text(
            "INSERT INTO priority_scores (cluster_id, score, factors, method, as_of) "
            "VALUES (:c, :s, CAST(:f AS jsonb), :m, :a)"
        ),
        {"c": cluster_id, "s": score, "f": json.dumps(factors, ensure_ascii=False), "m": cfg.method, "a": as_of},
    )
    session.execute(
        text(
            "UPDATE clusters SET appeals_count = :n, first_seen = :f, last_seen = :l WHERE id = :c"
        ),
        {"n": len(rows), "f": min(r.created_at for r in rows), "l": max(r.created_at for r in rows), "c": cluster_id},
    )
    return score


def on_category_changed(session: Session, appeal_id: int) -> int | None:
    """Категория обращения изменилась: кластер из одного обращения наследует её, приоритет пересчитывается."""
    row = session.execute(
        text("SELECT cluster_id, category_id FROM appeals WHERE id = :i"), {"i": appeal_id}
    ).first()
    if row is None:
        return None
    if row.cluster_id is None:
        return on_new_appeal(session, appeal_id)
    members = session.execute(
        text("SELECT count(*) FROM appeals WHERE cluster_id = :c"), {"c": row.cluster_id}
    ).scalar_one()
    if members == 1:
        session.execute(
            text("UPDATE clusters SET category_id = :cat WHERE id = :c"),
            {"cat": row.category_id, "c": row.cluster_id},
        )
    refresh_priority(session, row.cluster_id)
    return row.cluster_id


def on_status_changed(session: Session, appeal_id: int) -> str | None:
    """Кластер закрыт, когда все его обращения решены или отклонены; при повторном открытии приоритет пересчитывается."""
    cid = session.execute(text("SELECT cluster_id FROM appeals WHERE id = :i"), {"i": appeal_id}).scalar()
    if cid is None:
        return None
    still_open = session.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM appeals WHERE cluster_id = :c "
            "AND COALESCE(status, 'new') NOT IN ('resolved', 'rejected'))"
        ),
        {"c": cid},
    ).scalar_one()
    status = "open" if still_open else "closed"
    session.execute(text("UPDATE clusters SET status = :s WHERE id = :c"), {"s": status, "c": cid})
    if still_open:
        refresh_priority(session, cid)
    return status
