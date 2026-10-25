"""Импорт обращений из CSV/XLSX: разбор файла, проверка строк, запись в базу.

Обязательные колонки: text, created_at.
Необязательные: external_id, district, lat, lon, category, problem_id, subtopic.
Если category не указана, обращение загружается без категории (её определит классификатор).
"""
import csv
import io
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import column, table, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..schemas import ImportReport, RowError

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 50_000
MAX_TEXT = 5000
MAX_ERRORS_SHOWN = 50
CHUNK = 1000
LOCAL_TZ = timezone(timedelta(hours=5))  # Уфа, UTC+5: для дат без указания пояса

REQUIRED = ("text", "created_at")
OPTIONAL = ("external_id", "district", "lat", "lon", "category", "problem_id", "subtopic")
KNOWN = REQUIRED + OPTIONAL
DATE_FORMATS = (
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
)


class ImportFileError(ValueError):
    """Файл непригоден целиком: формат, кодировка, нет обязательных колонок."""


# ----------------------------- чтение файла -----------------------------

def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportFileError("Не удалось определить кодировку (ожидается UTF-8 или Windows-1251)")


def _read_csv(content: bytes) -> list[list]:
    body = _decode(content)
    if not body.strip():
        return []
    first = body.splitlines()[0]
    delim = max((";", ",", "\t"), key=first.count)
    if first.count(delim) == 0:
        raise ImportFileError("Не найден разделитель колонок (запятая, точка с запятой или табуляция)")
    return list(csv.reader(io.StringIO(body), delimiter=delim))


def _read_xlsx(content: bytes) -> list[list]:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - любой сбой чтения это непригодный файл
        raise ImportFileError("Не удалось прочитать файл Excel (.xlsx)") from exc
    try:
        rows: list[list] = []
        for r in wb.worksheets[0].iter_rows(values_only=True):
            rows.append(list(r))
            if len(rows) > MAX_ROWS + 1000:
                raise ImportFileError(f"В файле больше {MAX_ROWS} строк")
        return rows
    finally:
        wb.close()


def read_table(filename: str, content: bytes) -> list[tuple[int, dict]]:
    """Возвращает [(номер строки в файле, {колонка: значение})]. Заголовок это строка 1."""
    name = (filename or "").lower()
    if name.endswith((".csv", ".txt")):
        raw = _read_csv(content)
    elif name.endswith(".xlsx"):
        raw = _read_xlsx(content)
    else:
        raise ImportFileError("Поддерживаются файлы .csv и .xlsx")
    if not raw:
        raise ImportFileError("Файл пустой")

    header = [("" if c is None else str(c)).strip().lower() for c in raw[0]]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise ImportFileError("В файле нет обязательных колонок: " + ", ".join(missing))
    idx: dict[str, int] = {}
    for i, h in enumerate(header):
        if h in KNOWN and h not in idx:
            idx[h] = i

    records = []
    for n, r in enumerate(raw[1:], start=2):
        if all(c is None or str(c).strip() == "" for c in r):
            continue
        records.append((n, {k: (r[i] if i < len(r) else None) for k, i in idx.items()}))
    if len(records) > MAX_ROWS:
        raise ImportFileError(f"В файле больше {MAX_ROWS} строк")
    return records


# ----------------------------- проверка строк -----------------------------

def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _parse_dt(v) -> datetime:
    if isinstance(v, datetime):
        dt = v
    else:
        s = _s(v)
        if not s:
            raise ValueError("пустая дата")
        dt = None
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            for fmt in DATE_FORMATS:
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise ValueError(f"не удалось разобрать дату '{s}'")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    if dt.year < 2000:
        raise ValueError(f"дата слишком ранняя: {dt.date()}")
    if dt > datetime.now(timezone.utc) + timedelta(days=1):
        raise ValueError(f"дата в будущем: {dt.date()}")
    return dt


def _parse_float(v, name: str) -> float | None:
    s = _s(v).replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"{name}: не число '{s}'") from None


def validate_rows(
    records: list[tuple[int, dict]],
    categories: dict[str, int],
    districts: dict[str, int],
) -> tuple[list[dict], list[RowError]]:
    """categories и districts: имя в нижнем регистре -> id (категории и по коду, и по названию)."""
    valid: list[dict] = []
    errors: list[RowError] = []
    seen_ids: dict[str, int] = {}
    for n, r in records:
        try:
            body = _s(r.get("text"))
            if not body:
                raise ValueError("пустой текст")
            if len(body) > MAX_TEXT:
                raise ValueError(f"текст длиннее {MAX_TEXT} символов")
            created = _parse_dt(r.get("created_at"))

            ext = _s(r.get("external_id")) or None
            if ext and ext in seen_ids:
                raise ValueError(f"повтор external_id '{ext}' (первая строка {seen_ids[ext]})")

            cat_raw = _s(r.get("category"))
            cat_id = None
            if cat_raw:
                cat_id = categories.get(cat_raw.lower())
                if cat_id is None:
                    raise ValueError(f"неизвестная категория '{cat_raw}'")

            dist_raw = _s(r.get("district"))
            dist_id = None
            if dist_raw:
                dist_id = districts.get(dist_raw.lower())
                if dist_id is None:
                    raise ValueError(f"неизвестный район '{dist_raw}'")

            lat, lon = _parse_float(r.get("lat"), "lat"), _parse_float(r.get("lon"), "lon")
            if (lat is None) != (lon is None):
                raise ValueError("координаты: нужно указать и lat, и lon")
            if lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("координаты вне допустимого диапазона")

            valid.append({
                "external_id": ext, "text": body, "created_at": created,
                "district_id": dist_id, "lat": lat, "lon": lon, "category_id": cat_id,
                "problem_id": _s(r.get("problem_id")) or None,
                "subtopic": _s(r.get("subtopic")) or None,
            })
            if ext:
                seen_ids[ext] = n
        except ValueError as exc:
            errors.append(RowError(row=n, message=str(exc)))
    return valid, errors


# ----------------------------- запись в базу -----------------------------

_appeals = table(
    "appeals",
    column("batch_id"), column("external_id"), column("text"), column("created_at"),
    column("district_id"), column("lat"), column("lon"), column("category_id"),
    column("problem_id"), column("subtopic"),
)
_INSERT = pg_insert(_appeals).on_conflict_do_nothing(
    index_elements=["external_id"], index_where=text("external_id IS NOT NULL")
)


def run_import(session: Session, filename: str, content: bytes, dry_run: bool = False) -> ImportReport:
    filename = os.path.basename(filename or "upload")[:200]
    records = read_table(filename, content)

    categories: dict[str, int] = {}
    for code, name, cid in session.execute(text("SELECT code, name_ru, id FROM categories")):
        categories[code.strip().lower()] = cid
        categories[name.strip().lower()] = cid
    districts = {
        name.strip().lower(): did
        for name, did in session.execute(text("SELECT name, MIN(id) FROM districts GROUP BY name"))
    }

    valid, errors = validate_rows(records, categories, districts)

    ids = [r["external_id"] for r in valid if r["external_id"]]
    existing: set[str] = set()
    if ids:
        existing = {
            x[0] for x in session.execute(
                text("SELECT external_id FROM appeals WHERE external_id = ANY(:ids)"), {"ids": ids}
            )
        }
    new_rows = [r for r in valid if not (r["external_id"] and r["external_id"] in existing)]

    batch_id, inserted = None, 0
    if new_rows and not dry_run:
        batch_id = session.execute(
            text(
                "INSERT INTO import_batches (filename, source, rows_total, rows_ok, rows_failed) "
                "VALUES (:f, 'upload', :t, :ok, :bad) RETURNING id"
            ),
            {"f": filename, "t": len(records), "ok": len(new_rows), "bad": len(errors)},
        ).scalar_one()
        for i in range(0, len(new_rows), CHUNK):
            chunk = [dict(r, batch_id=batch_id) for r in new_rows[i:i + CHUNK]]
            session.execute(_INSERT, chunk)
            inserted += len(chunk)
        session.commit()
    else:
        session.rollback()  # ничего не меняли: закрываем транзакцию чтения

    return ImportReport(
        filename=filename, dry_run=dry_run, batch_id=batch_id,
        rows_total=len(records), rows_failed=len(errors),
        duplicates_skipped=len(valid) - len(new_rows), new_rows=len(new_rows), inserted=inserted,
        errors=errors[:MAX_ERRORS_SHOWN], errors_truncated=len(errors) > MAX_ERRORS_SHOWN,
    )
