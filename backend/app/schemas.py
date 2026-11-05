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


# ----------------------------- аналитика (шаг 3.3) -----------------------------

from datetime import date  # noqa: E402


class TimePoint(BaseModel):
    period: date  # начало периода (день, понедельник недели или 1-е число месяца)
    count: int


class TimeSeries(BaseModel):
    date_from: date
    date_to: date
    granularity: str
    category: str | None
    district: str | None
    total: int
    points: list[TimePoint]  # без пропусков: периоды без обращений дают count = 0


class CategoryStat(BaseModel):
    code: str
    name: str
    count: int
    prev_count: int
    change_pct: float | None  # None, если в прошлом периоде было 0
    share: float              # доля от всех обращений периода, 0..1


class DistrictStat(BaseModel):
    name: str
    count: int
    prev_count: int
    change_pct: float | None


class Summary(BaseModel):
    date_from: date
    date_to: date
    prev_date_from: date
    prev_date_to: date
    days: int
    total: int
    prev_total: int
    change_pct: float | None
    per_day: float
    uncategorized: int
    by_category: list[CategoryStat]
    by_district: list[DistrictStat]


class HeatmapCell(BaseModel):
    category: str
    district: str
    count: int


class Heatmap(BaseModel):
    date_from: date
    date_to: date
    categories: list[CategoryOut]
    districts: list[str]
    cells: list[HeatmapCell]  # только ненулевые ячейки


class MapPoint(BaseModel):
    id: int
    lat: float
    lon: float
    category: str | None
    district: str | None
    created_at: datetime


class MapPoints(BaseModel):
    total: int  # всего подходящих точек (может быть больше limit)
    items: list[MapPoint]


# ----------------------------- пользователи, вход, журнал (шаг 3.4) -----------------------------

from typing import Literal  # noqa: E402

Role = Literal["operator", "analyst", "manager", "admin", "executor"]


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    role: Role
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime | None
    department_id: int | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # секунд
    user: UserOut


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    role: Role
    department_id: int | None = None


class UserUpdate(BaseModel):
    role: Role | None = None
    full_name: str | None = None
    is_active: bool | None = None
    password: str | None = None  # сброс пароля администратором
    department_id: int | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class AuditEntry(BaseModel):
    id: int
    created_at: datetime
    user_id: int | None
    user_email: str | None
    action: str
    entity: str | None
    entity_id: str | None
    details: dict | None
    ip: str | None


class AuditPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuditEntry]
