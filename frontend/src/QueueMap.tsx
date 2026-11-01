import { useState } from 'react'
import { AttributionControl, CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import './dashboard.css'
import './queue.css'
import { apiFetch } from './api'
import { useAuth } from './auth'
import type { Category, ClusterDetails, District, QueueItem, QueuePage } from './types'
import { useFetch } from './useFetch'

const UFA: [number, number] = [54.74, 55.97]

const COLORS: Record<string, string> = {
  roads: '#e5484d',
  lighting: '#f5a524',
  transport: '#2f6fed',
  garbage: '#30a46c',
  utilities: '#8e4ec6',
  landscaping: '#12a594',
  other: '#8b8d98',
}
const colorOf = (code: string | null) => COLORS[code ?? ''] ?? '#8b8d98'
const radiusOf = (score: number) => 5 + (Math.min(Math.max(score, 0), 100) / 100) * 12

const LABELS: Record<string, string> = {
  urgency: 'Срочность по тексту',
  scale: 'Масштаб проблемы',
  significance: 'Значимость',
  dynamics: 'Динамика',
  age: 'Возраст',
}

function qs(params: Record<string, string>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v)
  const s = p.toString()
  return s ? `?${s}` : ''
}

function date(s: string | null | undefined): string {
  return s ? new Date(s).toLocaleDateString('ru-RU') : '—'
}

function detail(key: string, raw: Record<string, unknown>, category: string | null): string {
  switch (key) {
    case 'urgency':
      return `уровень срочности ${String(raw.urgency_level ?? '—')} из 3`
    case 'scale':
      return `обращений в проблеме: ${String(raw.appeals ?? '—')}`
    case 'dynamics':
      return `за последний период ${String(raw.recent ?? '—')}, за предыдущий ${String(raw.previous ?? '—')}`
    case 'age':
      return `проблеме ${typeof raw.age_days === 'number' ? raw.age_days.toFixed(1) : '—'} дн.`
    case 'significance':
      return `категория «${category ?? '—'}»${raw.social_object ? ', упомянут социальный объект' : ''}`
    default:
      return ''
  }
}

function ClusterCard({ id, onClose }: { id: number; onClose: () => void }) {
  const d = useFetch<ClusterDetails>(`/api/priority/clusters/${id}`)
  const c = d.data

  const rows = c?.factors
    ? Object.keys(c.factors.weights)
        .map((key) => {
          const w = c.factors!.weights[key] ?? 0
          const v = c.components[key] ?? 0
          return { key, w, v, pts: 100 * w * v }
        })
        .sort((a, b) => b.pts - a.pts)
    : []

  return (
    <section className="card">
      <div className="block-head">
        <h2>Карточка проблемы № {id}</h2>
        <button className="secondary" onClick={onClose}>
          Закрыть
        </button>
      </div>
      {d.error && <div className="alert">{d.error}</div>}
      {d.loading && <p className="muted">Загрузка…</p>}
      {c && (
        <div className="card-grid">
          <div>
            <p>
              <span className="dot" style={{ background: colorOf(c.category) }} />
              <strong>{c.category_name ?? c.category}</strong>, {c.district}
            </p>
            <p className="muted">
              Обращений: {c.appeals_count} · первое {date(c.first_seen)}, последнее {date(c.last_seen)}
              {c.centroid_lat != null && c.centroid_lon != null &&
                ` · координаты ${c.centroid_lat.toFixed(4)}, ${c.centroid_lon.toFixed(4)}`}
            </p>
            <p className="big-score">
              {c.score != null ? c.score.toFixed(1) : '—'} <span className="muted">из 100</span>
            </p>
            <h3>Из чего сложился балл</h3>
            {rows.length === 0 && <p className="muted">Оценка для этого кластера не рассчитана.</p>}
            {rows.map((r) => (
              <div className="comp" key={r.key}>
                <div className="comp-head">
                  <span>{LABELS[r.key] ?? r.key}</span>
                  <span>
                    {r.pts.toFixed(1)} <span className="muted">(вес {Math.round(r.w * 100)}%)</span>
                  </span>
                </div>
                <span className="bar wide">
                  <span style={{ width: `${Math.min(r.v, 1) * 100}%` }} />
                </span>
                <div className="muted note">
                  {detail(r.key, c.factors?.raw ?? {}, c.category_name ?? c.category)}
                </div>
              </div>
            ))}
            {c.factors && (
              <p className="muted note">
                Метод {c.factors.method}, расчёт на {date(c.factors.as_of)}. Балл = 100 × сумма (вес × значение
                фактора от 0 до 1).
              </p>
            )}
          </div>
          <div>
            <h3>Обращения в проблеме</h3>
            <ul className="appeals">
              {c.appeals.slice(0, 8).map((a) => (
                <li key={a.id}>
                  <span className="muted">{date(a.created_at)}</span> {a.text}
                </li>
              ))}
            </ul>
            {c.appeals.length > 8 && <p className="muted note">Показано 8 из {c.appeals.length}.</p>}
          </div>
        </div>
      )}
    </section>
  )
}

export default function QueueMap() {
  const { user } = useAuth()
  const canRecalc = user?.role === 'manager' || user?.role === 'admin'

  const [category, setCategory] = useState('')
  const [district, setDistrict] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [recalcDate, setRecalcDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const cats = useFetch<Category[]>('/api/categories')
  const dists = useFetch<District[]>('/api/districts')
  const queue = useFetch<QueuePage>(
    '/api/priority/queue' + qs({ category, district, limit: '200', r: String(reloadKey) }),
  )

  const items: QueueItem[] = queue.data?.items ?? []
  const onMap = items.filter((i) => i.centroid_lat != null && i.centroid_lon != null)
  const snapshot = items[0]?.as_of

  async function recalc() {
    setBusy(true)
    setMsg(null)
    try {
      const r = await apiFetch<{ processed_clusters: number }>(
        '/api/priority/recalculate' + qs({ as_of: recalcDate }),
        { method: 'POST' },
      )
      setMsg(`Пересчитано проблем: ${r.processed_clusters}`)
      setReloadKey((k) => k + 1)
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : 'Не удалось пересчитать')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack wide-stack">
      <div className="card toolbar">
        <label>
          Категория
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Все категории</option>
            {cats.data?.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Район
          <select value={district} onChange={(e) => setDistrict(e.target.value)}>
            <option value="">Все районы</option>
            {dists.data?.map((d) => (
              <option key={d.id} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        {canRecalc && (
          <>
            <label>
              Пересчёт на дату
              <input type="date" value={recalcDate} onChange={(e) => setRecalcDate(e.target.value)} />
            </label>
            <button disabled={busy} onClick={recalc}>
              {busy ? 'Считаем…' : 'Пересчитать приоритеты'}
            </button>
          </>
        )}
        <span className="muted note">
          {snapshot ? `Снимок приоритетов на ${date(snapshot)}. ` : ''}
          {queue.data ? `Проблем: ${queue.data.total}.` : ''}
          {msg ? ` ${msg}` : ''}
        </span>
      </div>

      {queue.error && <div className="alert">{queue.error}</div>}

      <div className="qm-layout">
        <div className="card map-card">
          <MapContainer
            center={UFA}
            zoom={11}
            className="map"
            scrollWheelZoom
            attributionControl={false}
          >
            <AttributionControl prefix={false} />
            <TileLayer
              attribution='&copy; участники <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {onMap.map((i) => (
              <CircleMarker
                key={i.cluster_id}
                center={[i.centroid_lat as number, i.centroid_lon as number]}
                radius={radiusOf(i.score)}
                pathOptions={{
                  color: i.cluster_id === selected ? '#ffffff' : colorOf(i.category),
                  weight: i.cluster_id === selected ? 3 : 1,
                  fillColor: colorOf(i.category),
                  fillOpacity: 0.7,
                }}
                eventHandlers={{ click: () => setSelected(i.cluster_id) }}
              >
                <Tooltip>
                  {i.category_name}, {i.district}: {i.score.toFixed(1)}
                </Tooltip>
              </CircleMarker>
            ))}
          </MapContainer>
          <div className="legend">
            {cats.data?.map((c) => (
              <span key={c.code}>
                <span className="dot" style={{ background: colorOf(c.code) }} />
                {c.name}
              </span>
            ))}
          </div>
          <p className="muted note">
            Размер маркера зависит от балла приоритета, цвет от категории. На карте до 200 самых приоритетных
            проблем.
          </p>
        </div>

        <div className="card">
          <div className="block-head">
            <h2>Очередь</h2>
          </div>
          {queue.loading && <p className="muted">Загрузка…</p>}
          {!queue.loading && items.length === 0 && !queue.error && (
            <p className="muted">Для выбранных условий проблем нет.</p>
          )}
          <div className="list">
            {items.slice(0, 50).map((i, n) => (
              <button
                key={i.cluster_id}
                className={i.cluster_id === selected ? 'row-btn active' : 'row-btn'}
                onClick={() => setSelected(i.cluster_id)}
              >
                <span className="rank">{n + 1}</span>
                <span className="dot" style={{ background: colorOf(i.category) }} />
                <span className="row-text">
                  {i.category_name}
                  <span className="muted"> · {i.district} · {i.appeals_count} обр.</span>
                </span>
                <strong>{i.score.toFixed(1)}</strong>
              </button>
            ))}
          </div>
        </div>
      </div>

      {selected !== null && <ClusterCard id={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
