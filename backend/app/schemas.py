from datetime import datetime

from pydantic import BaseModel


class RowError(BaseModel):
    row: int  # номер строки в файле (заголовок это строка 1)
    message: str


class ImportReport(BaseModel):
    filename: str
    dry_run: bool
    batch_id: int | None
    rows_total: int          # строк с данными в файле
    rows_failed: int         # строк с ошибками (не загружены)
    duplicates_skipped: int  # корректные строки, external_id которых уже есть в базе
    new_rows: int            # корректные новые строки (при dry_run: будут добавлены)
    inserted: int            # реально добавлено (при dry_run всегда 0)
    errors: list[RowError]   # первые 50 ошибок
    errors_truncated: bool


class AppealOut(BaseModel):
    id: int
    external_id: str | None
    text: str
    created_at: datetime
    district: str | None
    category: str | None  # код категории
    lat: float | None
    lon: float | None


class AppealsPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AppealOut]


class CategoryOut(BaseModel):
    code: str
    name: str


class DistrictOut(BaseModel):
    id: int
    name: str
