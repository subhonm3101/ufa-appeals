import { useState } from 'react'
import AppealCard from './AppealCard'
import { useAuth } from './auth'
import {
  STATUS_LABELS,
  STATUS_ORDER,
  fmtDate,
  fmtDateTime,
  personName,
  type CasePage,
  type CaseStatus,
} from './caseTypes'
import StatusBadge from './StatusBadge'
import type { Category, District } from './types'
import { useFetch } from './useFetch'
import './dashboard.css'
import './upload.css'
import './cases.css'

const LIMIT = 50

export default function Appeals() {
  const { user } = useAuth()
  const isExecutor = user?.role === 'executor'

  const cats = useFetch<Category[]>('/api/categories')
  const dists = useFetch<District[]>('/api/districts')

  const [category, setCategory] = useState('')
  const [district, setDistrict] = useState('')
  const [status, setStatus] = useState<CaseStatus | ''>('')
  const [onlyMine, setOnlyMine] = useState(false)
  const [overdue, setOverdue] = useState(false)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [sort, setSort] = useState('created')
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<number | null>(null)
  const [refresh, setRefresh] = useState(0)

  const params = new URLSearchParams({ limit: String(LIMIT), offset: String(offset), sort })
  if (category) params.set('category', category)
  if (district) params.set('district', district)
  if (status) params.set('status', status)
  if (onlyMine) params.set('assignee', 'me')
  if (overdue) params.set('overdue', 'true')
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  if (q) params.set('q', q)
  params.set('v', String(refresh))
  const page = useFetch<CasePage>('/api/cases?' + params.toString())

  // любое изменение фильтра возвращает список на первую страницу
  const filter = <T,>(set: (v: T) => void) => (v: T) => {
    set(v)
    setOffset(0)
  }

  function reset() {
    setCategory('')
    setDistrict('')
    setStatus('')
    setOnlyMine(false)
    setOverdue(false)
    setDateFrom('')
    setDateTo('')
    setSort('created')
    setQInput('')
    setQ('')
    setOffset(0)
  }

  const counts = page.data?.status_counts
  const allCount = counts ? STATUS_ORDER.reduce((sum, s) => sum + counts[s], 0) : 0
  const total = page.data?.total ?? 0
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + LIMIT, total)

  return (
    <div className="stack">
      <form
        className="card toolbar"
        onSubmit={(e) => {
          e.preventDefault()
          setQ(qInput.trim())
          setOffset(0)
        }}
      >
        <label>
          Категория
          <select value={category} onChange={(e) => filter(setCategory)(e.target.value)}>
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
          <select value={district} onChange={(e) => filter(setDistrict)(e.target.value)}>
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
          <input type="date" value={dateFrom} onChange={(e) => filter(setDateFrom)(e.target.value)} />
        </label>
        <label>
          По дату
          <input type="date" value={dateTo} onChange={(e) => filter(setDateTo)(e.target.value)} />
        </label>
        <label>
          Сортировка
          <select value={sort} onChange={(e) => filter(setSort)(e.target.value)}>
            <option value="created">Сначала новые</option>
            <option value="due">По сроку ответа</option>
          </select>
        </label>
        <label>
          Поиск по тексту или номеру
          <input
            type="search"
            value={qInput}
            maxLength={200}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="фонарь или UFA-2026-000123"
          />
        </label>
        {!isExecutor && (
          <label className="check">
            <input type="checkbox" checked={onlyMine} onChange={(e) => filter(setOnlyMine)(e.target.checked)} />
            Только мои
          </label>
        )}
        <label className="check">
          <input type="checkbox" checked={overdue} onChange={(e) => filter(setOverdue)(e.target.checked)} />
          Просроченные
        </label>
        <button type="submit">Найти</button>
        <button type="button" className="secondary" onClick={reset}>
          Сбросить
        </button>
      </form>

      {isExecutor && (
        <p className="muted note" style={{ margin: 0 }}>
          Вы видите только обращения, назначенные вам.
        </p>
      )}

      <div className="status-chips">
        <button className={status === '' ? 'chip active' : 'chip'} onClick={() => filter(setStatus)('')}>
          Все <small>{allCount}</small>
        </button>
        {STATUS_ORDER.map((s) => (
          <button key={s} className={status === s ? 'chip active' : 'chip'} onClick={() => filter(setStatus)(s)}>
            {STATUS_LABELS[s]} <small>{counts?.[s] ?? 0}</small>
          </button>
        ))}
      </div>

      <div className="card">
        {page.error && <p className="error">{page.error}</p>}
        <p className="muted note" style={{ marginTop: 0 }}>
          {page.loading ? 'Загрузка…' : `Найдено: ${total}. Показано ${from}–${to}.`}
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Номер</th>
                <th>Дата</th>
                <th>Статус</th>
                <th>Категория</th>
                <th>Район</th>
                <th>Исполнитель</th>
                <th>Срок</th>
                <th>Текст</th>
              </tr>
            </thead>
            <tbody>
              {page.data?.items.map((a) => (
                <tr
                  key={a.id}
                  className="clickable"
                  tabIndex={0}
                  onClick={() => setSelected(a.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') setSelected(a.id)
                  }}
                >
                  <td>{a.public_number}</td>
                  <td>{fmtDateTime(a.created_at)}</td>
                  <td>
                    <StatusBadge status={a.status} />
                  </td>
                  <td>{a.category_name ?? 'не определена'}</td>
                  <td>{a.district ?? '—'}</td>
                  <td>{a.assignee_id ? personName(a.assignee_name, a.assignee_email) : '—'}</td>
                  <td className={a.is_overdue ? 'overdue' : undefined}>{a.due_at ? fmtDate(a.due_at) : '—'}</td>
                  <td style={{ whiteSpace: 'normal', minWidth: 260 }}>{a.excerpt}</td>
                </tr>
              ))}
              {page.data && page.data.items.length === 0 && (
                <tr>
                  <td colSpan={8} className="muted">
                    По этим условиям обращений нет.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="upload-row">
          <button
            className="secondary"
            disabled={offset === 0 || page.loading}
            onClick={() => setOffset(Math.max(0, offset - LIMIT))}
          >
            Назад
          </button>
          <button
            className="secondary"
            disabled={offset + LIMIT >= total || page.loading}
            onClick={() => setOffset(offset + LIMIT)}
          >
            Вперёд
          </button>
        </div>
      </div>

      {selected !== null && (
        <AppealCard id={selected} onClose={() => setSelected(null)} onChanged={() => setRefresh((v) => v + 1)} />
      )}
    </div>
  )
}
