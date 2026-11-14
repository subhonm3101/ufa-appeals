FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --system --create-home --uid 10001 appuser

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts

# каталог фотографий обращений; модель категорий подключается снаружи (см. docker-compose.prod.yml)
RUN mkdir -p /app/uploads /app/models && chown -R appuser /app/uploads

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# при каждом запуске применяем миграции, затем стартует сервер
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --no-proxy-headers"]
