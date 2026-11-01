"""Нагрузочная проверка API: время ответа основных запросов и 10 параллельных пользователей.

Запуск (бэкенд должен работать на 127.0.0.1:8000):
    $env:CHECK_EMAIL="..."; $env:CHECK_PASSWORD="..."
    python backend\\scripts\\load_check.py
"""
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ.get("CHECK_URL", "http://127.0.0.1:8000")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # без системного прокси


def call(path, token=None, data=None):
    req = urllib.request.Request(BASE + path, data=data)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    t0 = time.perf_counter()
    with OPENER.open(req, timeout=120) as resp:
        body = resp.read()
    return time.perf_counter() - t0, len(body)


def login():
    email, password = os.environ.get("CHECK_EMAIL"), os.environ.get("CHECK_PASSWORD")
    if not email or not password:
        sys.exit("Задайте переменные CHECK_EMAIL и CHECK_PASSWORD")
    data = urllib.parse.urlencode({"username": email, "password": password}).encode()
    req = urllib.request.Request(BASE + "/api/auth/login", data=data)
    with OPENER.open(req, timeout=30) as resp:
        return json.load(resp)["access_token"]


ENDPOINTS = [
    ("Список обращений", "/api/appeals?limit=50"),
    ("Поиск по тексту", "/api/appeals?q=" + urllib.parse.quote("фонарь")),
    ("Сводка", "/api/analytics/summary"),
    ("Очередь приоритетов", "/api/priority/queue?limit=200"),
    ("Аномалии", "/api/anomalies"),
    ("Прогноз (неделя, город)", "/api/forecast?granularity=week"),
    ("Отчёт Excel", "/api/reports/summary.xlsx"),
]


def main():
    token = login()
    print(f"{'Запрос':28} {'мин':>7} {'медиана':>8} {'макс':>7}  размер")
    for name, path in ENDPOINTS:
        times, size = [], 0
        for _ in range(5):
            dt, size = call(path, token)
            times.append(dt)
        print(f"{name:28} {min(times):7.3f} {statistics.median(times):8.3f} {max(times):7.3f}  {size // 1024} КБ")

    print("\nПараллельные пользователи (на каждого по 5 запросов «Список обращений» и «Сводка», тайм-аут 15 с):")
    print(f"{'Польз.':>6} {'запросов':>9} {'ошибок':>7} {'всего, с':>9} {'запр/с':>7} {'медиана':>8} {'макс':>7}")
    paths = [ENDPOINTS[0][1], ENDPOINTS[2][1]] * 5
    for workers in (1, 2, 4, 8, 10):
        jobs = paths * workers
        results = []

        def one(p):
            t = time.perf_counter()
            try:
                OPENER.open(urllib.request.Request(BASE + p, headers={"Authorization": f"Bearer {token}"}), timeout=15).read()
                return time.perf_counter() - t, True
            except Exception:
                return time.perf_counter() - t, False

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, jobs))
        total = time.perf_counter() - t0
        ok = sorted(t for t, good in results if good)
        errors = sum(1 for _, good in results if not good)
        med = statistics.median(ok) if ok else float("nan")
        mx = ok[-1] if ok else float("nan")
        print(f"{workers:6} {len(jobs):9} {errors:7} {total:9.1f} {len(jobs) / total:7.1f} {med:8.3f} {mx:7.3f}")
        if errors:
            print("   есть ошибки, дальнейшие шаги остановлены")
            break


if __name__ == "__main__":
    main()
