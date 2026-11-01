import { useMemo, useState, type ReactNode } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import './dashboard.css'
import { downloadFile } from './api'
import type {
  AnomalyPage,
  Category,
  District,
  Forecast,
  Summary,
  Timeseries,
} from './types'
import { useFetch } from './useFetch'

function qs(params: Record<string, string>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v)
  const s = p.toString()
  return s ? `?${s}` : ''
}

function shiftDay(iso: string, delta: number): string {
  const [y, m, d] = iso.split('-').map(Number) as [number, number, number]
  return new Date(Date.UTC(y, m - 1, d + delta)).toISOString().slice(0, 10)
}

function shortDate(s: string): string {
  const parts = s.split('-')
  return parts.length === 3 ? `${parts[2]}.${parts[1]}` : s
}

function longDate(s: string): string {
  const parts = s.split('-')
  return parts.length === 3 ? `${parts[2]}.${parts[1]}.${parts[0]}` : s
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`
}

const AXIS = { fill: 'var(--muted)', fontSize: 12 }
const GRID = 'rgba(128, 128, 128, 0.25)'
const LINE = '#5b8cff'

function Block({
  title,
  controls,
  children,
}: {
  title: string
  controls?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="card">
      <div className="block-head">
        <h2>{title}</h2>
        {controls && <div className="controls">{controls}</div>}
      </div>
      {children}
    </section>
  )
}

function Status({ loading, error }: { loading: boolean; error: string | null }) {
  if (error) return <div className="alert">{error}</div>
  if (loading) return <p className="muted">Загрузка…</p>
  return null
}

export default function Dashboard() {
  const [category, setCategory] = useState('')
  const [district, setDistrict] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [gran, setGran] = useState('day')
  const [fcGran, setFcGran] = useState<'week' | 'day'>('week')
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const cats = useFetch<Category[]>('/api/categories')
  const dists = useFetch<District[]>('/api/districts')
  const base = useFetch<Summary>('/api/analytics/summary') // опорная дата: конец данных
  const anchor = base.data?.date_to

  const period = { date_from: dateFrom, date_to: dateTo }
  const summary = useFetch<Summary>('/api/analytics/summary' + qs(period))
  const ts = useFetch<Timeseries>(
    '/api/analytics/timeseries' + qs({ ...period, granularity: gran, category, district }),
  )
  const anomalies = useFetch<AnomalyPage>(
    '/api/anomalies' + qs({ ...period, category, district, limit: '200' }),
  )
  const pairSelected = Boolean(category && district)
  const forecast = useFetch<Forecast>(
    pairSelected ? null : '/api/forecast' + qs({ granularity: fcGran, category, district }),
  )

  function preset(days: number) {
    if (!anchor) return
    setDateTo(anchor)
    setDateFrom(shiftDay(anchor, -(days - 1)))
  }

  async function exportReport() {
    setExporting(true)
    setExportError(null)
    try {
      await downloadFile(
        '/api/reports/summary.xlsx' + qs({ date_from: dateFrom, date_to: dateTo, category, district }),
      )
    } catch (e: unknown) {
      setExportError(e instanceof Error ? e.message : 'Не удалось скачать отчёт')
    } finally {
      setExporting(false)
    }
  }

  const areas = useMemo(() => {
    const points = ts.data?.points ?? []
    if (gran !== 'day' || points.length === 0) return []
    const first = points[0]!.period
    const last = points[points.length - 1]!.period
    return (anomalies.data?.items ?? [])
      .filter((a) => a.end >= first && a.start <= last)
      .map((a) => ({
        key: `${a.category}-${a.district}-${a.start}`,
        x1: a.start < first ? first : a.start,
        x2: a.end > last ? last : a.end,
      }))
  }, [gran, ts.data, anomalies.data])

  const fcData = useMemo(
    () =>
      (forecast.data?.items ?? []).map((i) => ({
        date: i.target_date,
        value: i.value,
        band: [i.lower, i.upper] as [number, number],
      })),
    [forecast.data],
  )

  const fcMetrics = forecast.data?.model.metrics
  const level = forecast.data?.level
  const wapeKey =
    level === 'city' ? 'city_wape_pct' : level === 'category' ? 'categories_wape_pct' : 'districts_wape_pct'
  const wape = fcMetrics?.[wapeKey]
  const coverage = fcMetrics?.['city_coverage80_pct']

  const s = summary.data
  const catName = cats.data?.find((c) => c.code === category)?.name ?? 'все'

  return (
    <div className="stack">
      <p className="print-only">
        Отчёт по обращениям граждан, г. Уфа · категория: {catName} · район: {district || 'все'}
      </p>
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
        <label>
          С даты
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label>
          По дату
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <div className="chips">
          <button className="secondary" disabled={!anchor} onClick={() => preset(30)}>30 дней</button>
          <button className="secondary" disabled={!anchor} onClick={() => preset(90)}>90 дней</button>
          <button className="secondary" disabled={!anchor} onClick={() => preset(365)}>Год</button>
          <button
            className="secondary"
            onClick={() => {
              setDateFrom('')
              setDateTo('')
            }}
          >
            Сбросить период
          </button>
        </div>
        <div className="chips">
          <button disabled={exporting} onClick={exportReport}>
            {exporting ? 'Формируем…' : 'Скачать отчёт (Excel)'}
          </button>
          <button className="secondary" onClick={() => window.print()}>
            Печать / PDF
          </button>
        </div>
        {exportError && <div className="alert">{exportError}</div>}
      </div>

      <Status loading={summary.loading && !s} error={summary.error} />
      {s && (
        <div className="kpis">
          <div className="card kpi">
            <span className="muted">Обращений за период (город)</span>
            <strong>{s.total}</strong>
            <span className="muted">
              {longDate(s.date_from)} – {longDate(s.date_to)}
            </span>
          </div>
          <div className="card kpi">
            <span className="muted">В среднем в день</span>
            <strong>{s.per_day.toFixed(1)}</strong>
            <span className="muted">за {s.days} дн.</span>
          </div>
          <div className="card kpi">
            <span className="muted">К предыдущему периоду</span>
            <strong>{pct(s.change_pct)}</strong>
            <span className="muted">было {s.prev_total}</span>
          </div>
        </div>
      )}

      <Block
        title="Динамика обращений"
        controls={
          <select value={gran} onChange={(e) => setGran(e.target.value)} aria-label="Шаг графика">
            <option value="day">По дням</option>
            <option value="week">По неделям</option>
            <option value="month">По месяцам</option>
          </select>
        }
      >
        <Status loading={ts.loading} error={ts.error} />
        {ts.data && (
          <>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={ts.data.points} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="period" tickFormatter={shortDate} tick={AXIS} minTickGap={24} />
                <YAxis allowDecimals={false} tick={AXIS} width={36} />
                <Tooltip />
                {areas.map((a) => (
                  <ReferenceArea key={a.key} x1={a.x1} x2={a.x2} fill="#e5484d" fillOpacity={0.18} strokeOpacity={0} />
                ))}
                <Line type="monotone" dataKey="count" name="Обращений" stroke={LINE} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
            <p className="muted note">
              Всего {ts.data.total}.{' '}
              {gran === 'day' && areas.length > 0 && 'Красной заливкой отмечены найденные всплески.'}
            </p>
          </>
        )}
      </Block>

      <Block
        title="Прогноз нагрузки"
        controls={
          <select
            value={fcGran}
            onChange={(e) => setFcGran(e.target.value === 'day' ? 'day' : 'week')}
            aria-label="Шаг прогноза"
          >
            <option value="week">4 недели</option>
            <option value="day">28 дней</option>
          </select>
        }
      >
        {pairSelected && (
          <p className="muted">
            Прогноз по паре «категория × район» не публикуется: ряды слишком разрежены. Выберите
            либо категорию, либо район.
          </p>
        )}
        {!pairSelected && <Status loading={forecast.loading} error={forecast.error} />}
        {forecast.data && fcData.length === 0 && (
          <p className="muted">Для выбранного уровня прогноз не рассчитан.</p>
        )}
        {forecast.data && fcData.length > 0 && (
          <>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={fcData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={shortDate} tick={AXIS} minTickGap={24} />
                <YAxis allowDecimals={false} tick={AXIS} width={36} />
                <Tooltip />
                <Area dataKey="band" name="Интервал 80%" stroke="none" fill={LINE} fillOpacity={0.2} />
                <Line type="monotone" dataKey="value" name="Прогноз" stroke={LINE} strokeWidth={2} dot={fcGran === 'week'} />
              </ComposedChart>
            </ResponsiveContainer>
            <p className="muted note">
              {forecast.data.granularity === 'week' ? 'Недельные суммы' : 'Обращений в день'}, интервал 80%.
              Модель {forecast.data.model.name} ({forecast.data.model.version}).
              {typeof wape === 'number' && ` Ошибка на проверке (WAPE): ${wape}%.`}
              {typeof coverage === 'number' && forecast.data.level === 'city' &&
                ` Интервал накрыл ${coverage}% фактов.`}
            </p>
          </>
        )}
      </Block>

      <Block title="Аномалии: резкий рост обращений">
        <Status loading={anomalies.loading} error={anomalies.error} />
        {anomalies.data && anomalies.data.items.length === 0 && (
          <p className="muted">За выбранный период всплесков не найдено.</p>
        )}
        {anomalies.data && anomalies.data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Категория</th>
                  <th>Район</th>
                  <th>Период</th>
                  <th>Пик за 7 дней</th>
                  <th>Обычно</th>
                  <th>Оценка</th>
                </tr>
              </thead>
              <tbody>
                {anomalies.data.items.map((a) => (
                  <tr key={`${a.category}-${a.district}-${a.start}`}>
                    <td>{a.category_name ?? a.category}</td>
                    <td>{a.district}</td>
                    <td>
                      {shortDate(a.start)} – {shortDate(a.end)} ({a.days} дн.)
                    </td>
                    <td>{a.peak}</td>
                    <td>{a.expected}</td>
                    <td>
                      <span className="bar" title={`${a.score} из 10`}>
                        <span style={{ width: `${Math.min(a.score, 10) * 10}%` }} />
                      </span>{' '}
                      {a.score}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted note">
              Показано {anomalies.data.items.length} из {anomalies.data.total}. Считаются новые проблемы
              (кластеры похожих обращений), а не повторные жалобы на одну и ту же.
            </p>
          </div>
        )}
      </Block>

      {s && (
        <Block title="Структура по категориям (город)">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Категория</th>
                  <th>Обращений</th>
                  <th>Доля</th>
                  <th>К прошлому периоду</th>
                </tr>
              </thead>
              <tbody>
                {s.by_category.map((c) => (
                  <tr key={c.code}>
                    <td>{c.name}</td>
                    <td>{c.count}</td>
                    <td>
                      <span className="bar">
                        <span style={{ width: `${Math.round(c.share * 100)}%` }} />
                      </span>{' '}
                      {(c.share * 100).toFixed(1)}%
                    </td>
                    <td>{pct(c.change_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Block>
      )}
    </div>
  )
}
