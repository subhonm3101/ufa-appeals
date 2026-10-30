"""Шаг 5.2: страница для экспертной разметки приоритета кластеров.

    python backend/scripts/make_labeling_page.py

Создаёт:
  data/labeling/label.html     открыть двойным щелчком, оценки ставятся клавишами 1-5
  data/labeling/items_key.csv  КЛЮЧ (cluster_id и score формулы). Не открывать до конца разметки!
Выборка: 5 групп по score формулы, по 30 кластеров из каждой + 20 повторов для проверки устойчивости оценок.
"""
import argparse
import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sqlalchemy import text as sql

from app.db import SessionLocal
from app.services.priority_features import DEFAULT_CONFIG, compute_all


def stratified_sample(res, bins, per_bin, rng):
    """res отсортирован по score. Берём по per_bin случайных кластеров из каждой из bins равных частей."""
    n, chosen = len(res), []
    for b in range(bins):
        part = res[b * n // bins:(b + 1) * n // bins]
        chosen += rng.sample(part, min(per_bin, len(part)))
    return chosen


def district_names(s):
    cols = {r[0] for r in s.execute(sql(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'districts'"))}
    col = next((c for c in ("name_ru", "name", "title") if c in cols), None)
    if not col:
        return {}
    return {r[0]: r[1] for r in s.execute(sql(f"SELECT id, {col} FROM districts"))}


def order_items(base, repeats, rng):
    """Случайный порядок; повтор не ближе 25 позиций к оригиналу."""
    seq = [(c, False) for c in base] + [(c, True) for c in repeats]
    for _ in range(500):
        rng.shuffle(seq)
        pos = defaultdict(list)
        for i, (c, _) in enumerate(seq):
            pos[c].append(i)
        if all(len(p) == 1 or abs(p[0] - p[1]) >= 25 for p in pos.values()):
            break
    return seq


HTML = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Разметка приоритета</title>
<style>
:root{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--card:#fff;--line:#d6d3d1;--acc:#1d4ed8;--accfg:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#fafaf9;--mut:#a8a29e;--card:#292524;--line:#57534e;--acc:#60a5fa;--accfg:#0c0a09}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:16px}
.top{display:flex;justify-content:space-between;color:var(--mut);font-size:14px;margin-bottom:6px}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin-bottom:16px}
.bar>i{display:block;height:100%;background:var(--acc);width:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.meta{color:var(--mut);font-size:14px;margin-bottom:10px}
.ap{margin:0 0 10px;padding-left:10px;border-left:3px solid var(--line)}
.ap small{display:block;color:var(--mut)}
.more{color:var(--mut);font-size:14px}
.warn{color:#ef4444;min-height:1.5em;margin:10px 0 0}
.rate{display:grid;grid-template-columns:1fr;gap:8px;margin:8px 0}
button{font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;cursor:pointer}
.rate button{font-size:18px;font-weight:600;padding:12px 14px;text-align:left}
.rate button.sel{background:var(--acc);color:var(--accfg);border-color:var(--acc)}
.nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}
</style></head><body><main>
<div class="top"><span id="pos"></span><span id="done"></span></div>
<div class="bar"><i id="bar"></i></div>
<div class="card" id="card"></div>
<p class="warn" id="warn"></p>
<div class="rate" id="rate"></div>
<div class="nav"><button id="back">← Назад</button><button id="dl">Скачать CSV</button><button id="reset">Начать заново</button></div>
<p class="more">Оценивай как диспетчер: в какой срок это нужно решить. Клавиши 1–5 ставят оценку, ← возвращает назад.
Оценка принимается не раньше чем через 2 секунды после показа карточки.
Оценки хранятся в этом браузере, но скачивай CSV хотя бы раз в 30–40 обращений.</p>
</main><script>
window.addEventListener("error", e => {
  document.getElementById("card").textContent = "Ошибка страницы: " + e.message;
});
const ITEMS = __DATA__;
const LABEL = {5:"немедленно, угроза жизни или здоровью", 4:"серьёзно, устранить за 1–3 дня", 3:"устранить в течение недели",
               2:"плановое устранение, до месяца", 1:"не проблема: предложение или пожелание"};
function hash(s){let h=0;for(const c of s){h=(h*31+c.charCodeAt(0))|0}return h}
const KEY = "prio_label_" + hash(JSON.stringify(ITEMS));
let state = {ratings:{}, idx:0};
try { const s = localStorage.getItem(KEY); if (s) state = JSON.parse(s); } catch(e) {}
function save(){ try { localStorage.setItem(KEY, JSON.stringify(state)); } catch(e) {} }
let shownAt = Date.now();

function render(){
  document.getElementById("warn").textContent = "";
  const done = Object.keys(state.ratings).length;
  document.getElementById("done").textContent = "размечено " + done + " из " + ITEMS.length;
  document.getElementById("bar").style.width = (100 * done / ITEMS.length) + "%";
  const card = document.getElementById("card"); card.replaceChildren();
  const rate = document.getElementById("rate"); rate.replaceChildren();
  if (state.idx >= ITEMS.length){
    document.getElementById("pos").textContent = "Готово";
    const p = document.createElement("p");
    p.textContent = "Все " + ITEMS.length + " оценок поставлены. Нажми «Скачать CSV» и положи файл в папку data\\labeling_r2 под именем ratings.csv.";
    card.append(p); return;
  }
  const it = ITEMS[state.idx];
  document.getElementById("pos").textContent = "Обращение " + (state.idx + 1) + " из " + ITEMS.length;
  const meta = document.createElement("div"); meta.className = "meta";
  meta.textContent = it.category + " · " + it.district + " · обращений в кластере: " + it.n + " · проблеме " + it.age_days + " дн.";
  card.append(meta);
  it.texts.forEach(t => {
    const d = document.createElement("div"); d.className = "ap";
    const s = document.createElement("small"); s.textContent = t.date;
    d.append(s, document.createTextNode(t.text)); card.append(d);
  });
  if (it.more > 0){
    const m = document.createElement("div"); m.className = "more"; m.textContent = "…и ещё обращений: " + it.more; card.append(m);
  }
  const cur = state.ratings[it.id];
  for (let v = 5; v >= 1; v--){
    const b = document.createElement("button"); b.textContent = v + " — " + LABEL[v];
    if (cur && cur.r === v) b.className = "sel";
    b.onclick = () => rateItem(v); rate.append(b);
  }
  shownAt = Date.now();
}
function rateItem(v){
  if (state.idx >= ITEMS.length) return;
  if (Date.now() - shownAt < 2000){
    document.getElementById("warn").textContent = "Слишком быстро: прочитай карточку ещё раз";
    return;
  }
  const it = ITEMS[state.idx];
  const sec = Math.min(300, Math.round((Date.now() - shownAt) / 1000));
  state.ratings[it.id] = {r: v, t: sec, at: new Date().toISOString()};
  state.idx++; save(); render();
}
function back(){ if (state.idx > 0){ state.idx--; save(); render(); } }
function forward(){
  if (state.idx < ITEMS.length && state.ratings[ITEMS[state.idx].id]){ state.idx++; save(); render(); }
}
function download(){
  const lines = ["item_id,rating,seconds,rated_at"];
  ITEMS.forEach(it => { const r = state.ratings[it.id]; if (r) lines.push([it.id, r.r, r.t, r.at].join(",")); });
  const blob = new Blob([lines.join("\n") + "\n"], {type: "text/csv"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "ratings.csv";
  document.body.append(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
document.getElementById("back").onclick = back;
document.getElementById("dl").onclick = download;
document.getElementById("reset").onclick = () => {
  if (confirm("Стереть все оценки в этом браузере?")){ state = {ratings: {}, idx: 0}; save(); render(); }
};
document.addEventListener("keydown", e => {
  if (e.key >= "1" && e.key <= "5") rateItem(Number(e.key));
  else if (e.key === "ArrowLeft") back();
  else if (e.key === "ArrowRight") forward();
});
render();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-10-27T12:00:00+00:00")
    ap.add_argument("--bins", type=int, default=5)
    ap.add_argument("--per-bin", type=int, default=30)
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--from-key", default=None, help="items_key.csv прошлого раунда")
    ap.add_argument("--order-seed", type=int, default=7)
    ap.add_argument("--out", default="data/labeling")
    a = ap.parse_args()
    as_of = datetime.fromisoformat(a.as_of)
    rng = random.Random(a.seed)

    with SessionLocal() as s:
        res = compute_all(s, as_of, DEFAULT_CONFIG, save=False)
        if not res:
            sys.exit("Нет активных кластеров на эту дату")
        pool = res
        if a.from_key:
            with open(a.from_key, encoding="utf-8", newline="") as kf:
                allowed = {int(r["cluster_id"]) for r in csv.DictReader(kf) if r["is_repeat"] == "0"}
            pool = [r for r in res if r["cluster_id"] in allowed]
        sample = stratified_sample(pool, a.bins, a.per_bin, rng)
        ids = [r["cluster_id"] for r in sample]
        names = district_names(s)
        rows = s.execute(sql(
            "SELECT a.cluster_id, a.text, a.created_at, cl.district_id, c.name_ru "
            "FROM appeals a JOIN clusters cl ON cl.id = a.cluster_id "
            "JOIN categories c ON c.id = cl.category_id "
            "WHERE a.cluster_id = ANY(:ids) AND a.created_at <= :as_of ORDER BY a.created_at"),
            {"ids": ids, "as_of": as_of}).fetchall()

    by_cluster, meta = defaultdict(list), {}
    for cid, text, created, did, cat in rows:
        by_cluster[cid].append((text, created))
        meta[cid] = (cat, names.get(did, f"район {did}"))
    score = {r["cluster_id"]: r["score"] for r in sample}

    repeats = rng.sample(ids, min(a.repeats, len(ids)))
    seq = order_items(ids, repeats, random.Random(a.order_seed))

    items, key = [], []
    for i, (cid, is_rep) in enumerate(seq, 1):
        apps = by_cluster[cid]
        cat, dist = meta[cid]
        items.append({
            "id": f"Q{i:03d}", "category": cat, "district": dist, "n": len(apps),
            "age_days": (as_of - apps[0][1]).days,
            "texts": [{"date": (t + timedelta(hours=5)).strftime("%d.%m.%Y"), "text": x} for x, t in apps[:3]],
            "more": max(0, len(apps) - 3)})
        key.append((f"Q{i:03d}", cid, score[cid], int(is_rep)))

    os.makedirs(a.out, exist_ok=True)
    data = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    with open(os.path.join(a.out, "label.html"), "w", encoding="utf-8") as f:
        f.write(HTML.replace("__DATA__", data))
    with open(os.path.join(a.out, "items_key.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "cluster_id", "score", "is_repeat"])
        w.writerows(key)

    cats = Counter(meta[c][0] for c in ids)
    print(f"Кластеров в выборке: {len(ids)} из {len(res)} активных, повторов: {len(repeats)}, всего к разметке: {len(items)}")
    print("Категории: " + ", ".join(f"{k}: {v}" for k, v in cats.most_common()))
    print(f"Страница: {os.path.join(a.out, 'label.html')}")
    print("Ключ items_key.csv не открывай до конца разметки.")


if __name__ == "__main__":
    main()