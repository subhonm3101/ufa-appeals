"""Ограничение частоты запросов по ключу (адрес клиента, пользователь, ключ API).

RateLimiter хранит события в памяти процесса (для тестов и простых случаев).
DbRateLimiter хранит их в базе: счётчик общий для всех процессов сервера и
не сбрасывается при перезапуске.
"""
import random
import time
from collections import defaultdict, deque

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


class RateLimiter:
    """Не более `limit` событий за `window` секунд на каждый ключ."""

    def __init__(self, limit: int, window: float, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self.clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


class DbRateLimiter:
    """То же ограничение, но события лежат в таблице rate_hits.

    Проверка и запись идут в одной транзакции под блокировкой на пару «ограничитель, ключ»,
    поэтому параллельные запросы не могут пролезть сверх лимита. Если база недоступна,
    запрос пропускается: всё равно он упадёт на обращении к базе, а отказ от входа
    из-за сбоя счётчика ничего не защищает.
    """

    CLEANUP_CHANCE = 0.005

    def __init__(self, name: str, limit: int, window: float):
        self.name = name
        self.limit = limit
        self.window = window

    def allow(self, key) -> bool:
        from ..db import engine  # импорт здесь: модуль можно подключать без базы

        key = str(key)[:200]
        params = {"b": self.name, "k": key, "w": float(self.window)}
        try:
            with engine.begin() as conn:
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:l))"), {"l": f"{self.name}:{key}"})
                conn.execute(
                    text(
                        "DELETE FROM rate_hits WHERE bucket = :b AND key = :k "
                        "AND at < now() - make_interval(secs => :w)"
                    ),
                    params,
                )
                used = conn.execute(
                    text("SELECT count(*) FROM rate_hits WHERE bucket = :b AND key = :k"), params
                ).scalar_one()
                if used >= self.limit:
                    return False
                conn.execute(text("INSERT INTO rate_hits (bucket, key) VALUES (:b, :k)"), params)
                if random.random() < self.CLEANUP_CHANCE:
                    conn.execute(text("DELETE FROM rate_hits WHERE at < now() - interval '1 day'"))
                return True
        except SQLAlchemyError:
            return True

    def reset(self) -> None:
        from ..db import engine

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rate_hits WHERE bucket = :b"), {"b": self.name})
