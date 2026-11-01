import { useState } from 'react'
import './dashboard.css'
import './upload.css'
import type { Category, District } from './types'
import { useFetch } from './useFetch'

interface AppealItem {
  id: number
  external_id: string | null
  text: string
  created_at: string
  district: string | null
  category: string | null
  lat: number | null
  lon: number | null
}

interface AppealsPage {
  total: number
  limit: number
  offset: number
  items: AppealItem[]
}

const LIMIT = 50

function fmt(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function Appeals() {
  const cats = useFetch<Category[]>('/api/categories')
  const dists = useFetch<District[]>('/api/districts')

  const [category, setCategory] = useState('')
  const [district, setDistrict] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)

  const params = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) })
  if (category) params.set('category', category)
  if (district) params.set('district', district)
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  if (q) params.set('q', q)
  const page = useFetch<AppealsPage>('/api/appeals?' + params.toString())

  const catName = (code: string | null) =>
    cats.data?.find((c) => c.code === code)?.name ?? code ?? 'не определена'

  // любое изменение фильтра возвращает список на первую страницу
  const change = (set: (v: string) => void) => (v: string) => {
    set(v)
    setOffset(0)
  }

  function reset() {
    setCategory('')
    setDistrict('')
    setDateFrom('')
    setDateTo('')
    setQInput('')
    setQ('')
    setOffset(0)
  }

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
          <select value={category} onChange={(e) => change(setCategory)(e.target.value)}>
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
          <select value={district} onChange={(e) => change(setDistrict)(e.target.value)}>
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
          <input type="date" value={dateFrom} onChange={(e) => change(setDateFrom)(e.target.value)} />
        </label>
        <label>
          По дату
          <input type="date" value={dateTo} onChange={(e) => change(setDateTo)(e.target.value)} />
        </label>
        <label>
          Поиск по тексту
          <input
            type="search"
            value={qInput}
            maxLength={200}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="например, фонарь"
          />
        </label>
        <button type="submit">Найти</button>
        <button type="button" className="secondary" onClick={reset}>
          Сбросить
        </button>
      </form>

      <div className="card">
        {page.error && <p className="error">{page.error}</p>}
        <p className="muted note" style={{ marginTop: 0 }}>
          {page.loading ? 'Загрузка…' : `Найдено: ${total}. Показано ${from}–${to}.`}
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Категория</th>
                <th>Район</th>
                <th>Текст</th>
              </tr>
            </thead>
            <tbody>
              {page.data?.items.map((a) => (
                <tr key={a.id}>
                  <td>{fmt(a.created_at)}</td>
                  <td>{catName(a.category)}</td>
                  <td>{a.district ?? '—'}</td>
                  <td style={{ whiteSpace: 'normal', minWidth: 280 }}>{a.text}</td>
                </tr>
              ))}
              {page.data && page.data.items.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
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
    </div>
  )
}
