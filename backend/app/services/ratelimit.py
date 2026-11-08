"""Ограничение частоты запросов по ключу (адрес клиента). Хранится в памяти процесса."""
import time
from collections import defaultdict, deque


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
