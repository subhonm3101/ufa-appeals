import { useState, type FormEvent } from 'react'
import { apiFetch, ApiError } from './api'
import { useFetch } from './useFetch'
import './public.css'

interface District {
  id: number
  name: string
}

interface PublicStatus {
  public_number: string
  status: string
  status_label: string
  category: string | null
  created_at: string
  due_at: string | null
  resolved_at: string | null
  response_text: string | null
}

const MIN_TEXT = 20
const MAX_TEXT = 5000
const MAX_PHOTOS = 3
const MAX_PHOTO_MB = 5

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru-RU', { timeZone: 'Asia/Yekaterinburg' })
}

function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : 'Не удалось выполнить запрос'
}

export function SubmitForm() {
  const districts = useFetch<District[]>('/api/public/districts')
  const [text, setText] = useState('')
  const [address, setAddress] = useState('')
  const [email, setEmail] = useState('')
  const [districtId, setDistrictId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [number, setNumber] = useState<string | null>(null)
  const [photos, setPhotos] = useState<File[]>([])

  function addPhotos(list: FileList | null) {
    if (!list) return
    const next = [...photos]
    for (const f of Array.from(list)) {
      if (next.length >= MAX_PHOTOS) {
        setError(`Можно приложить не больше ${MAX_PHOTOS} фотографий.`)
        break
      }
      if (f.size > MAX_PHOTO_MB * 1024 * 1024) {
        setError(`Файл «${f.name}» больше ${MAX_PHOTO_MB} МБ.`)
        continue
      }
      setError(null)
      next.push(f)
    }
    setPhotos(next)
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('text', text)
      if (address) form.append('address_text', address)
      if (email) form.append('contact_email', email)
      if (districtId) form.append('district_id', districtId)
      for (const f of photos) form.append('files', f)
      const res = await apiFetch<{ public_number: string }>('/api/public/appeals', {
        method: 'POST',
        body: form,
      })
      setNumber(res.public_number)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  if (number) {
    return (
      <div className="card">
        <h2>Обращение зарегистрировано</h2>
        <p>Ваш номер:</p>
        <p className="public-number">{number}</p>
        <p className="muted">Сохраните номер: по нему можно проверить, на каком этапе обращение.</p>
        <button
          className="secondary"
          onClick={() => {
            setNumber(null)
            setText('')
            setAddress('')
            setEmail('')
            setDistrictId('')
            setPhotos([])
          }}
        >
          Подать ещё одно
        </button>
      </div>
    )
  }

  return (
    <form className="card public-form" onSubmit={submit}>
      <h2>Подать обращение</h2>
      <label>
        Опишите проблему
        <textarea
          rows={6}
          value={text}
          maxLength={MAX_TEXT}
          onChange={(e) => setText(e.target.value)}
          required
        />
      </label>
      <span className="muted">
        {text.trim().length < MIN_TEXT
          ? `Ещё минимум ${MIN_TEXT - text.trim().length} символов`
          : `${text.length} из ${MAX_TEXT}`}
      </span>
      <label>
        Район (необязательно)
        <select value={districtId} onChange={(e) => setDistrictId(e.target.value)}>
          <option value="">Не указан</option>
          {(districts.data ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Адрес (необязательно)
        <input value={address} maxLength={300} onChange={(e) => setAddress(e.target.value)} />
      </label>
      <label>
        Электронная почта для связи (необязательно)
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Фотографии (необязательно, до {MAX_PHOTOS} шт., JPEG, PNG или WebP)
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          disabled={photos.length >= MAX_PHOTOS}
          onChange={(e) => {
            addPhotos(e.target.files)
            e.target.value = ''
          }}
        />
      </label>
      {photos.length > 0 && (
        <ul className="public-photos">
          {photos.map((f, i) => (
            <li key={`${f.name}-${i}`}>
              <span>{f.name}</span>
              <button
                type="button"
                className="secondary"
                onClick={() => setPhotos(photos.filter((_, j) => j !== i))}
              >
                Убрать
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="error">{error}</p>}
      <div>
        <button type="submit" disabled={busy || text.trim().length < MIN_TEXT}>
          {busy ? 'Отправляем…' : 'Отправить'}
        </button>
      </div>
    </form>
  )
}

function StatusCheck() {
  const [number, setNumber] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<PublicStatus | null>(null)

  async function check(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(
        await apiFetch<PublicStatus>(
          `/api/public/appeals/${encodeURIComponent(number.trim())}`,
        ),
      )
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card public-form" onSubmit={check}>
      <h2>Проверить статус</h2>
      <label>
        Номер обращения
        <input
          value={number}
          placeholder="UFA-2026-000123"
          onChange={(e) => setNumber(e.target.value)}
          required
        />
      </label>
      {error && <p className="error">{error}</p>}
      <div>
        <button type="submit" disabled={busy || !number.trim()}>
          {busy ? 'Ищем…' : 'Проверить'}
        </button>
      </div>
      {result && (
        <dl className="public-result">
          <dt>Номер</dt>
          <dd>{result.public_number}</dd>
          <dt>Статус</dt>
          <dd>
            <strong>{result.status_label}</strong>
          </dd>
          <dt>Тема</dt>
          <dd>{result.category ?? 'определяется'}</dd>
          <dt>Зарегистрировано</dt>
          <dd>{fmtDate(result.created_at)}</dd>
          <dt>Срок ответа</dt>
          <dd>{fmtDate(result.due_at)}</dd>
          {result.response_text && (
            <>
              <dt>Ответ</dt>
              <dd>{result.response_text}</dd>
            </>
          )}
        </dl>
      )}
    </form>
  )
}

export default function PublicPage() {
  return (
    <div className="public-shell">
      <header className="public-head">
        <strong>Обращения граждан · Уфа</strong>
        <span>
          <a href="#/account">Вход и регистрация</a> · <a href="#/">Для сотрудников</a>
        </span>
      </header>
      <div className="public-grid">
        <SubmitForm />
        <StatusCheck />
      </div>
    </div>
  )
}
