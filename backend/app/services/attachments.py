"""Вложения к обращениям: проверка изображений и хранение файлов на диске."""
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from .intake import IntakeError

MAX_FILES = 3
MAX_SIZE = 5 * 1024 * 1024
UPLOAD_DIR = Path(
    os.environ.get("APPEALS_UPLOAD_DIR") or Path(__file__).resolve().parents[2] / "uploads"
)


@dataclass
class Checked:
    name: str
    data: bytes
    content_type: str
    ext: str


def detect(data: bytes) -> tuple[str, str] | None:
    """Определяет тип по содержимому файла, а не по имени или заголовку запроса."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def _safe_name(name: str | None) -> str:
    base = re.sub(r"[^\w.\- ]", "_", os.path.basename(name or "photo"), flags=re.UNICODE).strip()
    return (base or "photo")[:120]


def check_files(files: list[tuple[str | None, bytes]]) -> list[Checked]:
    """Проверяет число, размер и тип файлов; при ошибке бросает IntakeError."""
    if len(files) > MAX_FILES:
        raise IntakeError(f"Можно приложить не больше {MAX_FILES} фотографий.")
    result = []
    for name, data in files:
        shown = _safe_name(name)
        if not data:
            raise IntakeError(f"Файл «{shown}» пустой.")
        if len(data) > MAX_SIZE:
            raise IntakeError(f"Файл «{shown}» больше {MAX_SIZE // (1024 * 1024)} МБ.")
        kind = detect(data)
        if not kind:
            raise IntakeError(f"Файл «{shown}» не похож на фотографию: нужен JPEG, PNG или WebP.")
        result.append(Checked(shown, data, kind[0], kind[1]))
    return result


def save(session: Session, appeal_id: int, files: list[Checked]) -> None:
    """Пишет файлы на диск и сведения о них в базу; фиксирует транзакцию."""
    if not files:
        return
    folder = UPLOAD_DIR / str(appeal_id)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        for f in files:
            storage = f"{appeal_id}/{uuid.uuid4().hex}.{f.ext}"
            (UPLOAD_DIR / storage).write_bytes(f.data)
            written.append(UPLOAD_DIR / storage)
            session.execute(
                text(
                    "INSERT INTO appeal_attachments "
                    "(appeal_id, original_name, content_type, size_bytes, storage_name) "
                    "VALUES (:a, :n, :c, :s, :p)"
                ),
                {"a": appeal_id, "n": f.name, "c": f.content_type, "s": len(f.data), "p": storage},
            )
        session.commit()
    except Exception:
        session.rollback()
        for p in written:
            p.unlink(missing_ok=True)
        raise
