"""Журнал действий: кто, что и когда сделал."""
import json

from sqlalchemy import text
from sqlalchemy.orm import Session


def log_event(
    session: Session, user_id: int | None, action: str, entity: str | None = None,
    entity_id: object = None, details: dict | None = None, ip: str | None = None,
) -> None:
    """Пишет событие и фиксирует транзакцию (вместе с изменениями, сделанными в ней до этого)."""
    session.execute(
        text(
            "INSERT INTO audit_log (user_id, action, entity, entity_id, details, ip) "
            "VALUES (:u, :a, :e, :i, CAST(:d AS jsonb), :ip)"
        ),
        {
            "u": user_id, "a": action, "e": entity,
            "i": None if entity_id is None else str(entity_id),
            "d": json.dumps(details, ensure_ascii=False, default=str) if details is not None else None,
            "ip": ip,
        },
    )
    session.commit()
