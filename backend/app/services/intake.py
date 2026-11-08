"""Регистрация нового обращения: одна точка входа для сайта, оператора и внешнего API."""
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

SOURCES = ("web", "operator", "api")
MIN_TEXT = 20
MAX_TEXT = 5000
MAX_ADDRESS = 300
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class IntakeError(ValueError):
    """Данные обращения не прошли проверку; message можно показать пользователю."""


@dataclass
class NewAppeal:
    text: str
    source: str = "web"
    address_text: str | None = None
    contact_email: str | None = None
    district_id: int | None = None
    lat: float | None = None
    lon: float | None = None
    external_id: str | None = None


@dataclass
class Registered:
    id: int
    public_number: str


def clean(data: NewAppeal) -> NewAppeal:
    """Проверяет и нормализует данные; при ошибке бросает IntakeError."""
    body = " ".join((data.text or "").split())
    if len(body) < MIN_TEXT:
        raise IntakeError(f"Опишите проблему подробнее: минимум {MIN_TEXT} символов.")
    if len(body) > MAX_TEXT:
        raise IntakeError(f"Текст слишком длинный: максимум {MAX_TEXT} символов.")
    if data.source not in SOURCES:
        raise IntakeError("Неизвестный источник обращения.")
    address = " ".join((data.address_text or "").split()) or None
    if address and len(address) > MAX_ADDRESS:
        raise IntakeError(f"Адрес слишком длинный: максимум {MAX_ADDRESS} символов.")
    email = (data.contact_email or "").strip().lower() or None
    if email and (len(email) > 254 or not _EMAIL.match(email)):
        raise IntakeError("Укажите корректный адрес электронной почты.")
    if (data.lat is None) != (data.lon is None):
        raise IntakeError("Координаты нужно указать парой: широта и долгота.")
    if data.lat is not None and not (-90 <= data.lat <= 90 and -180 <= data.lon <= 180):
        raise IntakeError("Координаты вне допустимого диапазона.")
    external = (data.external_id or "").strip() or None
    return NewAppeal(body, data.source, address, email, data.district_id, data.lat, data.lon, external)


def register(session: Session, data: NewAppeal) -> Registered:
    """Сохраняет обращение со статусом «new» и записью в истории; фиксирует транзакцию."""
    d = clean(data)
    if d.district_id is not None:
        found = session.execute(
            text("SELECT 1 FROM districts WHERE id = :i"), {"i": d.district_id}
        ).first()
        if not found:
            raise IntakeError("Неизвестный район.")
    if d.external_id is not None:
        dup = session.execute(
            text("SELECT id, public_number FROM appeals WHERE external_id = :e"),
            {"e": d.external_id},
        ).first()
        if dup:
            return Registered(dup.id, dup.public_number)
    row = session.execute(
        text(
            "INSERT INTO appeals (text, created_at, source, address_text, contact_email, "
            "district_id, lat, lon, external_id, status) "
            "VALUES (:t, now(), :s, :a, :e, :d, :lat, :lon, :x, 'new') "
            "RETURNING id, public_number"
        ),
        {"t": d.text, "s": d.source, "a": d.address_text, "e": d.contact_email,
         "d": d.district_id, "lat": d.lat, "lon": d.lon, "x": d.external_id},
    ).one()
    session.execute(
        text(
            "INSERT INTO appeal_status_history (appeal_id, from_status, to_status, comment) "
            "VALUES (:i, NULL, 'new', :c)"
        ),
        {"i": row.id, "c": "Обращение зарегистрировано"},
    )
    session.commit()
    return Registered(row.id, row.public_number)
