import { useState, type FormEvent } from 'react'
import { ApiError, apiFetch } from './api'
import { useAuth } from './auth'
import { fmtDate, fmtDateTime } from './caseTypes'
import NotificationBell from './NotificationBell'
import { SubmitForm } from './PublicPage'
import { useFetch } from './useFetch'
import './cases.css'
import './public.css'
import './cabinet.css'

interface MyItem {
  public_number: string
  status: string
  status_label: string
  category: string | null
  created_at: string
  due_at: string | null
  excerpt: string
}

interface MyDetail {
  public_number: string
  status: string
  status_label: string
  text: string
  address_text: string | null
  category: string | null
  district: string | null
  created_at: string
  due_at: string | null
  resolved_at: string | null
  response_text: string | null
  reject_reason: string | null
  can_comment: boolean
  history: { status: string; status_label: string; at: string }[]
  messages: { body: string; at: string; mine: boolean }[]
}

function Status({ status, label }: { status: string; label: string }) {
  return <span className={`st st-${status}`}>{label}</span>
}

function MyAppeal({ number, onBack }: { number: string; onBack: () => void }) {
  const [version, setVersion] = useState(0)
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const detail = useFetch<MyDetail>(`/api/my/appeals/${number}?v=${version}`)
  const d = detail.data

  async function send(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await apiFetch(`/api/my/appeals/${number}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body }),
      })
      setBody('')
      setVersion((v) => v + 1)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось отправить сообщение')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card cabinet-detail">
      <button className="secondary" onClick={onBack}>
        ← К списку
      </button>
      {detail.error && <p className="error">{detail.error}</p>}
      {!d && !detail.error && <p className="muted">Загрузка…</p>}
      {d && (
        <>
          <h2>
            {d.public_number} <Status status={d.status} label={d.status_label} />
          </h2>
          <dl className="public-result">
            <dt>Зарегистрировано</dt>
            <dd>{fmtDateTime(d.created_at)}</dd>
            <dt>Срок ответа</dt>
            <dd>{d.due_at ? fmtDate(d.due_at) : 'будет установлен после принятия'}</dd>
            <dt>Тема</dt>
            <dd>{d.category ?? 'определяется'}</dd>
            {d.district && (
              <>
                <dt>Район</dt>
                <dd>{d.district}</dd>
              </>
            )}
            {d.address_text && (
              <>
                <dt>Адрес</dt>
                <dd>{d.address_text}</dd>
              </>
            )}
          </dl>

          <h3>Ваше обращение</h3>
          <div className="appeal-text">{d.text}</div>

          {d.response_text && (
            <>
              <h3>Ответ</h3>
              <div className="appeal-text">{d.response_text}</div>
            </>
          )}
          {d.reject_reason && (
            <>
              <h3>Причина отклонения</h3>
              <div className="appeal-text">{d.reject_reason}</div>
            </>
          )}

          <h3>Ход рассмотрения</h3>
          <ul className="cabinet-list">
            {d.history.map((h, i) => (
              <li key={i}>
                <span className="muted">{fmtDateTime(h.at)}</span> · {h.status_label}
              </li>
            ))}
          </ul>

          <h3>Переписка</h3>
          {d.messages.length === 0 && <p className="muted">Сообщений пока нет.</p>}
          <ul className="cabinet-messages">
            {d.messages.map((m, i) => (
              <li key={i} className={m.mine ? 'mine' : 'staff'}>
                <small className="muted">
                  {m.mine ? 'Вы' : 'Сотрудник'} · {fmtDateTime(m.at)}
                </small>
                <div>{m.body}</div>
              </li>
            ))}
          </ul>

          {d.can_comment ? (
            <form className="public-form" onSubmit={send}>
              <label>
                Дополнить обращение
                <textarea rows={3} maxLength={2000} value={body} onChange={(e) => setBody(e.target.value)} />
              </label>
              {error && <p className="error">{error}</p>}
              <div>
                <button type="submit" disabled={busy || !body.trim()}>
                  {busy ? 'Отправляем…' : 'Отправить'}
                </button>
              </div>
            </form>
          ) : (
            <p className="muted">Обращение закрыто: дополнить его нельзя. Если вопрос остался, подайте новое обращение.</p>
          )}
        </>
      )}
    </div>
  )
}

function MyList({ onOpen }: { onOpen: (number: string) => void }) {
  const list = useFetch<MyItem[]>('/api/my/appeals')
  return (
    <div className="card">
      <h2>Мои обращения</h2>
      {list.error && <p className="error">{list.error}</p>}
      {list.loading && <p className="muted">Загрузка…</p>}
      {list.data && list.data.length === 0 && (
        <p className="muted">Вы ещё не подавали обращений. Перейдите во вкладку «Подать обращение».</p>
      )}
      {list.data && list.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Номер</th>
                <th>Дата</th>
                <th>Статус</th>
                <th>Тема</th>
                <th>Текст</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((a) => (
                <tr
                  key={a.public_number}
                  className="clickable"
                  tabIndex={0}
                  onClick={() => onOpen(a.public_number)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') onOpen(a.public_number)
                  }}
                >
                  <td>{a.public_number}</td>
                  <td>{fmtDate(a.created_at)}</td>
                  <td>
                    <Status status={a.status} label={a.status_label} />
                  </td>
                  <td>{a.category ?? 'определяется'}</td>
                  <td style={{ whiteSpace: 'normal', minWidth: 220 }}>{a.excerpt}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function CitizenCabinet() {
  const { user, logout } = useAuth()
  const [tab, setTab] = useState<'list' | 'new'>('list')
  const [open, setOpen] = useState<string | null>(null)

  return (
    <div className="public-shell">
      <header className="public-head">
        <strong>Личный кабинет · {user?.full_name || user?.email}</strong>
        <div className="cabinet-actions">
          <NotificationBell
            onOpenAppeal={(_id, number) => {
              if (!number) return
              setTab('list')
              setOpen(number)
            }}
          />
          <button className="secondary" onClick={logout}>
            Выйти
          </button>
        </div>
      </header>
      <nav className="menu" aria-label="Разделы кабинета">
        <button
          className={tab === 'list' ? 'menu-item active' : 'menu-item'}
          onClick={() => {
            setTab('list')
            setOpen(null)
          }}
        >
          Мои обращения
        </button>
        <button className={tab === 'new' ? 'menu-item active' : 'menu-item'} onClick={() => setTab('new')}>
          Подать обращение
        </button>
      </nav>
      <div className="cabinet-body">
        {tab === 'new' ? <SubmitForm /> : open ? <MyAppeal number={open} onBack={() => setOpen(null)} /> : <MyList onOpen={setOpen} />}
      </div>
    </div>
  )
}
