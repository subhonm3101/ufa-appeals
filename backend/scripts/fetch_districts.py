"""Шаг 14.10: скачивает границы районов Уфы из OpenStreetMap (через Nominatim) в GeoJSON.

    python backend/scripts/fetch_districts.py

Данные © участники OpenStreetMap, лицензия ODbL. Результат: backend/migrations/ufa_districts.geojson
"""
import json
import os
import time
import urllib.parse
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "migrations", "ufa_districts.geojson")
NAMES = ["Дёмский", "Калининский", "Кировский", "Ленинский", "Октябрьский", "Орджоникидзевский", "Советский"]
LAT = (54.40, 55.10)
LON = (55.55, 56.45)
UA = "ufa-appeals-diploma/1.0 (student project; contact via GitHub subhonm3101/ufa-appeals)"


def search(query: str):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query, "format": "jsonv2", "polygon_geojson": 1, "polygon_threshold": 0.0003,
        "limit": 5, "accept-language": "ru"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def inside_ufa(item) -> bool:
    s, n, w, e = (float(x) for x in item["boundingbox"])
    return LAT[0] <= (s + n) / 2 <= LAT[1] and LON[0] <= (w + e) / 2 <= LON[1]


def main():
    features = []
    for name in NAMES:
        found = None
        for variant in dict.fromkeys([name, name.replace("ё", "е")]):
            for item in search(f"{variant} район, Уфа"):
                geo = item.get("geojson") or {}
                if geo.get("type") in ("Polygon", "MultiPolygon") and inside_ufa(item):
                    found = item
                    break
            time.sleep(1.2)
            if found:
                break
        if not found:
            print(f"НЕ НАЙДЕНО: {name}")
            continue
        geo = found["geojson"]
        print(f"{name}: {found['display_name'][:80]} | {geo['type']}")
        features.append({"type": "Feature", "properties": {"name": name}, "geometry": geo})
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)
    print(f"Сохранено районов: {len(features)} из {len(NAMES)} -> {os.path.normpath(OUT)} "
          f"({os.path.getsize(OUT) // 1024} КБ)")


if __name__ == "__main__":
    main()
