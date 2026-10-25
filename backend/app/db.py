from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

# pool_pre_ping: проверяет соединение перед использованием (база могла перезапуститься)
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session():
    """Зависимость FastAPI: одна сессия на запрос."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
