import { useState } from 'react'
import { apiFetch, ApiError, ROLE_LABELS, type Role, type User } from './api'
import './dashboard.css'
import './upload.css'
import { useFetch } from './useFetch'

interface AuditEntry {
  id: number
  created_at: string
  user_id: number | null
  user_email: string | null
  action: string
  entity: string | null
  entity_id: string | null
  details: Record<string, unknown> | null
  ip: string | null
}

interface AuditPage {
  total: number
  limit: number
  offset: number
  items: AuditEntry[]
}

const ROLES = Object.keys(ROLE_LABELS) as Role[]
const LIMIT = 50

function fmt(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function Users() {
  const [version, setVersion] = useState(0)
  const users = useFetch<User[]>(`/api/users?v=${version}`)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ email: '', full_name: '', password: '', role: 'operator' as Role })

  async function call(path: string, method: string, body: unknown) {
    setError(null)
    try {
      await apiFetch(path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      setVersion((v) => v + 1)
      return true
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось выполнить запрос')
      return false
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault()
    const ok = await call('/api/users', 'POST', {
      email: form.email.trim(),
      password: form.password,
      full_name: form.full_name.trim() || null,
      role: form.role,
    })
    if (ok) setForm({ email: '', full_name: '', password: '', role: 'operator' })
  }

  function resetPassword(u: User) {
    const password = window.prompt(`Новый пароль для ${u.email}:`)
    if (password) void call(`/api/users/${u.id}`, 'PATCH', { password })
  }

  return (
    <div className="card">
      <div className="block-head">
        <h2>Пользователи</h2>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Почта</th>
              <th>Имя</th>
              <th>Роль</th>
              <th>Активен</th>
              <th>Последний вход</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id}>
                <td>{u.email}</td>
                <td>{u.full_name ?? '—'}</td>
                <td>
                  <select
                    value={u.role}
                    onChange={(e) => void call(`/api/users/${u.id}`, 'PATCH', { role: e.target.value })}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r]}
                      </option>
                    ))}
                  </select>
                </td>
                <td>{u.is_active ? 'да' : 'нет'}</td>
                <td>{fmt(u.last_login_at)}</td>
                <td>
                  <button
                    className="secondary"
                    onClick={() => void call(`/api/users/${u.id}`, 'PATCH', { is_active: !u.is_active })}
                  >
                    {u.is_active ? 'Отключить' : 'Включить'}
                  </button>{' '}
                  <button className="secondary" onClick={() => resetPassword(u)}>
                    Сменить пароль
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Новый пользователь</h3>
      <form className="toolbar" onSubmit={create}>
        <label>
          Почта
          <input
            type="email"
            required
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </label>
        <label>
          Имя
          <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        </label>
        <label>
          Пароль
          <input
            type="password"
            required
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </label>
        <label>
          Роль
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Создать</button>
      </form>
    </div>
  )
}

function Audit() {
  const [offset, setOffset] = useState(0)
  const page = useFetch<AuditPage>(`/api/audit?limit=${LIMIT}&offset=${offset}`)
  const total = page.data?.total ?? 0

  return (
    <div className="card">
      <div className="block-head">
        <h2>Журнал действий</h2>
      </div>
      {page.error && <p className="error">{page.error}</p>}
      <p className="muted note" style={{ marginTop: 0 }}>
        {page.loading ? 'Загрузка…' : `Записей: ${total}. Новые сверху.`}
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Время</th>
              <th>Пользователь</th>
              <th>Действие</th>
              <th>Объект</th>
              <th>Детали</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            {page.data?.items.map((a) => (
              <tr key={a.id}>
                <td>{fmt(a.created_at)}</td>
                <td>{a.user_email ?? '—'}</td>
                <td>{a.action}</td>
                <td>{[a.entity, a.entity_id].filter(Boolean).join(' #') || '—'}</td>
                <td style={{ whiteSpace: 'normal', maxWidth: 360, fontSize: '0.85rem' }}>
                  {a.details ? JSON.stringify(a.details) : '—'}
                </td>
                <td>{a.ip ?? '—'}</td>
              </tr>
            ))}
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
  )
}

export default function Admin() {
  return (
    <div className="stack">
      <Users />
      <Audit />
    </div>
  )
}
