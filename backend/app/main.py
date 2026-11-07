import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .api.analytics import router as analytics_router
from .api.appeals import router as appeals_router
from .api.auth import router as auth_router
from .api.users import router as users_router
from .api.priority import router as priority_router
from .api.forecast import router as forecast_router
from .api.anomalies import router as anomalies_router
from .api.reports import router as reports_router
from .api.cases import router as cases_router
from .api.notifications import router as notifications_router
from .auth import get_current_user
from .config import DEFAULT_SECRET_KEY, settings
from .db import get_session

if settings.secret_key == DEFAULT_SECRET_KEY:
    logging.getLogger("uvicorn.error").warning(
        "Используется ключ подписи токенов по умолчанию. Задайте свой через APPEALS_SECRET_KEY "
        "(переменная окружения или файл .env), иначе токены может подделать любой."
    )

app = FastAPI(title="Ufa Appeals API", version="0.2.0")

# Разрешаем запросы с фронтенда на этапе разработки (React dev-сервер)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(appeals_router)
app.include_router(analytics_router)
app.include_router(users_router)
app.include_router(priority_router)
app.include_router(forecast_router)
app.include_router(anomalies_router)
app.include_router(reports_router)
app.include_router(cases_router)
app.include_router(notifications_router)


@app.get("/health")
def health():
    """Сервер работает (базу не трогает). Открыт без входа, для проверки состояния."""
    return {"status": "ok"}


@app.get("/health/db")
def health_db(session: Session = Depends(get_session)):
    """Проверка подключения к PostgreSQL. Открыт без входа."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    return {"status": "ok", "database": "connected"}


@app.get("/api/stats/categories", dependencies=[Depends(get_current_user)])
def stats_categories(session: Session = Depends(get_session)):
    """Число обращений по категориям. Требует входа."""
    try:
        rows = session.execute(
            text(
                "SELECT c.code, c.name_ru, COUNT(a.id) AS cnt "
                "FROM categories c LEFT JOIN appeals a ON a.category_id = c.id "
                "GROUP BY c.code, c.name_ru ORDER BY cnt DESC"
            )
        ).all()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    return [{"code": r.code, "name": r.name_ru, "count": r.cnt} for r in rows]

