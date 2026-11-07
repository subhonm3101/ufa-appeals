"""Правила обработки обращения: статусы, допустимые переходы, права, срок ответа.

Модуль не обращается к базе и не знает про HTTP, поэтому его правила
проверяются обычными модульными тестами.
"""
from datetime import datetime, timedelta

STATUSES = ("new", "accepted", "in_progress", "waiting", "resolved", "rejected")

STATUS_LABELS = {
    "new": "Новое",
    "accepted": "Принято",
    "in_progress": "В работе",
    "waiting": "Ожидает ответа",
    "resolved": "Решено",
    "rejected": "Отклонено",
}

CLOSED = frozenset({"resolved", "rejected"})

# Срок рассмотрения по умолчанию, календарных дней с даты регистрации.
RESPONSE_DAYS = 30
# За сколько дней до срока исполнитель получает напоминание.
DUE_SOON_DAYS = 3

TRANSITIONS = {
    "new": ("accepted", "rejected"),
    "accepted": ("in_progress", "rejected"),
    "in_progress": ("waiting", "resolved", "rejected"),
    "waiting": ("in_progress", "resolved", "rejected"),
    "resolved": ("in_progress",),
    "rejected": ("accepted",),
}

STATUS_CHANGERS = ("operator", "manager", "admin", "executor")
REOPENERS = ("manager", "admin")
EXECUTOR_TARGETS = frozenset({"in_progress", "waiting", "resolved"})


def due_date(created_at: datetime) -> datetime:
    """Срок исполнения обращения."""
    return created_at + timedelta(days=RESPONSE_DAYS)


def check_transition(
    current: str,
    target: str,
    role: str,
    is_assignee: bool,
    comment: str | None,
    response_text: str | None,
) -> tuple[int, str] | None:
    """None, если переход разрешён, иначе (HTTP-код, сообщение)."""
    if target == current:
        return 409, "Обращение уже находится в этом статусе"
    if target not in TRANSITIONS.get(current, ()):
        return 409, (
            f"Нельзя перевести обращение из статуса «{STATUS_LABELS[current]}» "
            f"в статус «{STATUS_LABELS[target]}»"
        )
    if current in CLOSED and role not in REOPENERS:
        return 403, "Возобновить закрытое обращение может только руководитель или администратор"
    if role == "executor":
        if not is_assignee:
            return 403, "Исполнитель может менять только назначенные ему обращения"
        if target not in EXECUTOR_TARGETS:
            return 403, "Исполнитель может перевести обращение только в работу, в ожидание или в решённые"
    if target == "rejected" and not (comment or "").strip():
        return 422, "Укажите причину отклонения"
    if target == "resolved" and not (response_text or "").strip():
        return 422, "Для решённого обращения нужен текст ответа"
    return None


def allowed_transitions(current: str, role: str, is_assignee: bool) -> list[str]:
    """Статусы, в которые этот пользователь может перевести обращение (для кнопок в интерфейсе)."""
    if role not in STATUS_CHANGERS:
        return []
    return [
        target
        for target in TRANSITIONS.get(current, ())
        if check_transition(current, target, role, is_assignee, "x", "x") is None
    ]
