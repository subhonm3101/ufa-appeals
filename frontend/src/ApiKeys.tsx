import { useState, type FormEvent } from 'react'
import { ApiError, apiFetch } from './api'
import { fmtDateTime } from './caseTypes'
import { useFetch } from './useFetch'
import './dashboard.css'
import './apikeys.css'

interface KeyRow {
  id: number
  name: string
  prefix: string
  is_active: boolean
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export default function ApiKeys() {
  const [version, setVersion] = useState(0)
  const keys = useFetch<KeyRow[]>(`/api/api-keys?v=${version}`)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fresh, setFresh] = useState<{ name: string; key: string } | null>(null)
  const [copied, setCopied] = useState(false)

  async function create(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = await apiFetch<{ name: string; key: string }>('/api/api-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      setFresh({ name: r.name, key: r.key })
      setCopied(false)
      setName('')
      setVersion((v) => v + 1)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось выпустить ключ')
    } finally {
      setBusy(false)
    }
  }

  async function revoke(k: KeyRow) {
    if (!window.confirm(`Отозвать ключ «${k.name}»? Система, которая им пользуется, перестанет работать.`)) return
    setError(null)
    try {
      await apiFetch(`/api/api-keys/${k.id}/revoke`, { method: 'POST' })
      setVersion((v) => v + 1)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось отозвать ключ')
    }
  }

  async function copy() {
    if (!fresh) return
    try {
      await navigator.clipboard.writeText(fresh.key)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="card">
      <h2>Ключи внешнего API</h2>
      <p className="muted">
        Ключ нужен внешней системе, чтобы передавать обращения в сервис. Выпускайте отдельный ключ для каждой системы:
        так его можно отозвать, не затрагивая остальные.
      </p>

      <form className="keys-form" onSubmit={create}>
        <input
          placeholder="Название, например «Портал администрации»"
          maxLength={100}
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="Название ключа"
        />
        <button type="submit" disabled={busy || !name.trim()}>
          {busy ? 'Выпускаем…' : 'Выпустить ключ'}
        </button>
      </form>
      {error && <p className="error">{error}</p>}

      {fresh && (
        <div className="key-fresh" role="status">
          <strong>Ключ «{fresh.name}» выпущен.</strong> Скопируйте его сейчас: потом он нигде не будет показан.
          <code>{fresh.key}</code>
          <div>
            <button className="secondary" onClick={copy}>
              {copied ? 'Скопировано' : 'Копировать'}
            </button>{' '}
            <button className="secondary" onClick={() => setFresh(null)}>
              Скрыть
            </button>
          </div>
        </div>
      )}

      {keys.error && <p className="error">{keys.error}</p>}
      {keys.loading && <p className="muted">Загрузка…</p>}
      {keys.data && keys.data.length === 0 && <p className="muted">Ключей пока нет.</p>}
      {keys.data && keys.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Название</th>
                <th>Начало ключа</th>
                <th>Создан</th>
                <th>Последнее использование</th>
                <th>Состояние</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {keys.data.map((k) => (
                <tr key={k.id}>
                  <td>{k.name}</td>
                  <td>
                    <code>{k.prefix}…</code>
                  </td>
                  <td>{fmtDateTime(k.created_at)}</td>
                  <td>{k.last_used_at ? fmtDateTime(k.last_used_at) : 'не использовался'}</td>
                  <td>{k.is_active ? 'Действует' : `Отозван ${k.revoked_at ? fmtDateTime(k.revoked_at) : ''}`}</td>
                  <td>
                    {k.is_active && (
                      <button className="secondary" onClick={() => revoke(k)}>
                        Отозвать
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>Как передать обращение</h3>
      <pre className="key-example">{`curl -X POST https://<адрес-сервиса>/api/external/appeals \\
  -H "X-API-Key: <ключ>" -H "Content-Type: application/json" \\
  -d '{"external_id": "12345", "text": "Текст обращения не короче 20 символов"}'`}</pre>
      <p className="muted">
        Повторная отправка с тем же <code>external_id</code> не создаёт дубль. Статус:{' '}
        <code>GET /api/external/appeals/UFA-…</code> с тем же заголовком.
      </p>
    </div>
  )
}
