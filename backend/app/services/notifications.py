"""Уведомления внутри системы: создание и проверка сроков."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import workflow

KINDS = ("assigned", "status_changed", "due_soon", "overdue")
MANAGER_ROLES = ("manager", "admin")


def notify(session: Session, user_id: int, appeal_id: int | None, kind: str, message: str) -> None:
    """Добавляет уведомление в текущую транзакцию (фиксирует вызывающий код)."""
    assert kind in KINDS, kind
    session.execute(
        text(
            "INSERT INTO notifications (user_id, appeal_id, kind, message) "
            "VALUES (:u, :a, :k, :m)"
        ),
        {"u": user_id, "a": appeal_id, "k": kind, "m": message},
    )


_OPEN = "COALESCE(a.status, 'new') NOT IN ('resolved', 'rejected')"


def refresh_deadlines(session: Session, user_id: int, role: str) -> None:
    """Создаёт напоминания о сроках для пользователя; каждое приходит один раз.

    Повтор исключает уникальный индекс по (пользователь, обращение, вид).
    Назначенные обращения: «срок истекает» и «просрочено».
    Руководитель и администратор получают «просрочено» по всем обращениям.
    """
    params = {"uid": user_id, "days": workflow.DUE_SOON_DAYS}
    insert = "INSERT INTO notifications (user_id, appeal_id, kind, message) "
    when = "to_char(a.due_at AT TIME ZONE 'Asia/Yekaterinburg', 'DD.MM.YYYY')"
    session.execute(
        text(
            insert
            + f"SELECT CAST(:uid AS integer), a.id, 'due_soon', "
            f"'Срок ответа по обращению ' || a.public_number || ' истекает ' || {when} "
            f"FROM appeals a WHERE a.assignee_id = :uid AND a.due_at >= now() "
            f"AND a.due_at < now() + make_interval(days => :days) AND {_OPEN} "
            "ON CONFLICT DO NOTHING"
        ),
        params,
    )
    scope = "TRUE" if role in MANAGER_ROLES else "a.assignee_id = :uid"
    session.execute(
        text(
            insert
            + f"SELECT CAST(:uid AS integer), a.id, 'overdue', "
            f"'Просрочено обращение ' || a.public_number || ' (срок был ' || {when} || ')' "
            f"FROM appeals a WHERE {scope} AND a.due_at < now() AND {_OPEN} "
            "ON CONFLICT DO NOTHING"
        ),
        params,
    )
    session.commit()
