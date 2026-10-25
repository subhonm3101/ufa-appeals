from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .api.analytics import router as analytics_router
from .api.appeals import router as appeals_router
from .db import get_session

app = FastAPI(title="Ufa Appeals API", version="0.1.0")

# Разрешаем запросы с фронтенда на этапе разработки (React dev-сервер)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(appeals_router)
app.include_router(analytics_router)


@app.get("/health")
def health():
    """Сервер работает (базу не трогает)."""
    return {"status": "ok"}


@app.get("/health/db")
def health_db(session: Session = Depends(get_session)):
    """Проверка подключения к PostgreSQL."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    return {"status": "ok", "database": "connected"}


@app.get("/api/stats/categories")
def stats_categories(session: Session = Depends(get_session)):
    """Число обращений по категориям (первый реальный запрос к данным)."""
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
