import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from './api'
import { useAuth } from './auth'
import {
  CLOSED,
  SOURCE_LABELS,
  STATUS_LABELS,
  fmtDate,
  fmtDateTime,
  personName,
  type CaseCard,
  type CaseStatus,
  type Department,
  type Executor,
} from './caseTypes'
import AppealPhotos from './AppealPhotos'
import StatusBadge from './StatusBadge'
import type { Category } from './types'
import { useFetch } from './useFetch'
import './dashboard.css'
import './cases.css'
import './review.css'

type Run = (path: string, body: unknown) => Promise<boolean>

const ASSIGNERS = ['operator', 'manager', 'admin']
const COMMENTERS = ['operator', 'manager', 'admin', 'executor']

function StatusActions({ card, busy, run }: { card: CaseCard; busy: boolean; run: Run }) {
  const [target, setTarget] = useState<CaseStatus | null>(null)
  const [comment, setComment] = useState('')
  const [response, setResponse] = useState(card.response_text ?? '')

  if (card.allowed_transitions.length === 0) {
    return <p className="muted">Для вашей роли смена статуса сейчас недоступна.</p>
  }

  async function submit() {
    if (!target) return
    const ok = await run(`/api/appeals/${card.id}/status`, {
      to_status: target,
      comment: comment.trim() || null,
      response_text: target === 'resolved' ? response.trim() || null : null,
    })
    if (ok) {
      setTarget(null)
      setComment('')
    }
  }

  return (
    <>
      <div className="action-row">
        {card.allowed_transitions.map((s) => (
          <button
            key={s}
            className={s === target ? '' : 'secondary'}
            disabled={busy}
            onClick={() => setTarget(s === target ? null : s)}
          >
            {STATUS_LABELS[s]}
          </button>
        ))}
      </div>
      {target && (
        <div className="form-stack">
          {target === 'resolved' && (
            <label>
              Текст ответа заявителю (обязательно)
              <textarea value={response} onChange={(e) => setResponse(e.target.value)} maxLength={5000} />
            </label>
          )}
          <label>
            {target === 'rejected' ? 'Причина отклонения (обязательно)' : 'Комментарий (необязательно)'}
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
          </label>
          <div className="action-row">
            <button disabled={busy} onClick={submit}>
              Перевести в статус «{STATUS_LABELS[target]}»
            </button>
            <button className="secondary" disabled={busy} onClick={() => setTarget(null)}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </>
  )
}

function AssignForm({ card, busy, run }: { card: CaseCard; busy: boolean; run: Run }) {
  const departments = useFetch<Department[]>('/api/departments')
  const [dep, setDep] = useState(card.department_id?.toString() ?? '')
  const [exec, setExec] = useState(card.assignee_id?.toString() ?? '')
  const [note, setNote] = useState<string | null>(null)
  const executors = useFetch<Executor[]>(
    dep ? `/api/executors?department_id=${dep}` : '/api/executors',
  )

  function changeDepartment(value: string) {
    setDep(value)
    setNote(null)
    // исполнитель сохраняется только если подразделение вернули к исходному
    const original = card.department_id?.toString() ?? ''
    setExec(value === original ? (card.assignee_id?.toString() ?? '') : '')
  }

  async function submit() {
    const depId = dep ? Number(dep) : null
    const execId = exec ? Number(exec) : null
    const body: Record<string, number | null> = {}
    if (depId !== card.department_id) body.department_id = depId
    if (execId !== card.assignee_id) body.assignee_id = execId
    if (Object.keys(body).length === 0) {
      setNote('Ничего не изменено')
      return
    }
    setNote(null)
    await run(`/api/appeals/${card.id}/assign`, body)
  }

  const list = executors.data ?? []
  const hasCurrent = list.some((e) => e.id === card.assignee_id)

  return (
    <div className="form-stack">
      <label>
        Подразделение
        <select value={dep} onChange={(e) => changeDepartment(e.target.value)}>
          <option value="">Не указано</option>
          {departments.data?.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Исполнитель
        <select value={exec} onChange={(e) => { setExec(e.target.value); setNote(null) }}>
          <option value="">Не назначен</option>
          {card.assignee_id && !hasCurrent && dep === (card.department_id?.toString() ?? '') && (
            <option value={card.assignee_id}>{personName(card.assignee_name, card.assignee_email)}</option>
          )}
          {list.map((e) => (
            <option key={e.id} value={e.id}>
              {personName(e.full_name, e.email)}
            </option>
          ))}
        </select>
      </label>
      {list.length === 0 && !executors.loading && (
        <p className="muted note">
          В этом подразделении исполнителей нет. Выберите другое подразделение или создайте пользователя с ролью
          «Исполнитель» в разделе «Пользователи и журнал».
        </p>
      )}
      <div className="action-row">
        <button disabled={busy} onClick={submit}>
          Сохранить назначение
        </button>
      </div>
      {note && <p className="muted note">{note}</p>}
    </div>
  )
}

function Comments({ card, canWrite, busy, run }: { card: CaseCard; canWrite: boolean; busy: boolean; run: Run }) {
  const [body, setBody] = useState('')
  const [isPublic, setIsPublic] = useState(false)

  async function submit() {
    if (!body.trim()) return
    const ok = await run(`/api/appeals/${card.id}/comments`, { body, is_internal: !isPublic })
    if (ok) setBody('')
  }

  return (
    <>
      {card.comments.length === 0 ? (
        <p className="muted">Комментариев пока нет.</p>
      ) : (
        <ul className="timeline">
          {card.comments.map((c) => (
            <li key={c.id}>
              <div className="when">
                {fmtDateTime(c.created_at)} · {c.author ?? '—'} ·{' '}
                <span className="comment-internal">{c.is_internal ? 'внутренний' : 'публичный'}</span>
              </div>
              {c.body}
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <div className="form-stack">
          <label>
            Новый комментарий
            <textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000} />
          </label>
          <label className="check">
            <input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} />
            Публичный (виден заявителю)
          </label>
          <div className="action-row">
            <button disabled={busy || !body.trim()} onClick={submit}>
              Добавить комментарий
            </button>
          </div>
        </div>
      )}
    </>
  )
}

interface Props {
  id: number
  onClose: () => void
  onChanged: () => void
}

function ReviewBox({ card, busy, run, canEdit }: { card: CaseCard; busy: boolean; run: Run; canEdit: boolean }) {
  const cats = useFetch<Category[]>('/api/categories')
  const [other, setOther] = useState('')
  const s = card.suggestion
  const path = `/api/appeals/${card.id}/category`

  return (
    <div className="review-box">
      <p>
        <strong>Требуется проверка категории.</strong>{' '}
        {s
          ? `Модель предлагает «${s.category_name}», уверенность ${Math.round(s.confidence * 100)}%.`
          : 'Модель не смогла определить категорию.'}
      </p>
      {canEdit ? (
        <div className="review-row">
          {s && (
            <button disabled={busy} onClick={() => run(path, { category_code: s.category })}>
              Подтвердить
            </button>
          )}
          <select value={other} onChange={(e) => setOther(e.target.value)}>
            <option value="">Выбрать другую категорию…</option>
            {cats.data?.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
          <button className="secondary" disabled={busy || !other} onClick={() => run(path, { category_code: other })}>
            Назначить
          </button>
        </div>
      ) : (
        <p className="muted">Категорию определяет оператор.</p>
      )}
    </div>
  )
}

export default function AppealCard({ id, onClose, onChanged }: Props) {
  const { user } = useAuth()
  const role = user?.role ?? ''
  const [version, setVersion] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const card = useFetch<CaseCard>(`/api/appeals/${id}?v=${version}`)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const run: Run = async (path, body) => {
    setBusy(true)
    setError(null)
    try {
      await apiFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      setVersion((v) => v + 1)
      onChanged()
      return true
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось выполнить запрос')
      return false
    } finally {
      setBusy(false)
    }
  }

  const c = card.data
  const closed = c ? CLOSED.includes(c.status) : false

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Карточка обращения">
        <div className="drawer-head">
          <div>
            <h2>{c ? c.public_number : 'Обращение'}</h2>
            {c && <StatusBadge status={c.status} />}
          </div>
          <button className="secondary" onClick={onClose}>
            Закрыть
          </button>
        </div>

        {card.error && <p className="error">{card.error}</p>}
        {!c && !card.error && <p className="muted">Загрузка…</p>}
        {error && <p className="error">{error}</p>}

        {c && (
          <>
            <dl className="info-grid">
              <dt>Зарегистрировано</dt>
              <dd>{fmtDateTime(c.created_at)}</dd>
              <dt>Срок ответа</dt>
              <dd className={c.is_overdue ? 'overdue' : undefined}>
                {c.due_at ? fmtDate(c.due_at) : 'не установлен'}
                {c.is_overdue ? ' · просрочено' : ''}
              </dd>
              <dt>Категория</dt>
              <dd>{c.category_name ?? 'не определена'}</dd>
              <dt>Район</dt>
              <dd>{c.district ?? '—'}</dd>
              <dt>Адрес</dt>
              <dd>{c.address_text ?? '—'}</dd>
              <dt>Подразделение</dt>
              <dd>{c.department_name ?? '—'}</dd>
              <dt>Исполнитель</dt>
              <dd>{c.assignee_id ? personName(c.assignee_name, c.assignee_email) : 'не назначен'}</dd>
              <dt>Источник</dt>
              <dd>{SOURCE_LABELS[c.source] ?? c.source}</dd>
              {c.resolved_at && (
                <>
                  <dt>Решено</dt>
                  <dd>{fmtDateTime(c.resolved_at)}</dd>
                </>
              )}
            </dl>

            {c.needs_review && (
              <ReviewBox key={`r-${c.id}`} card={c} busy={busy} run={run} canEdit={ASSIGNERS.includes(role)} />
            )}

            <h3>Текст обращения</h3>
            <div className="appeal-text">{c.text}</div>

            <AppealPhotos key={`p-${c.id}`} appealId={c.id} />

            {c.response_text && (
              <>
                <h3>Ответ заявителю</h3>
                <div className="appeal-text">{c.response_text}</div>
              </>
            )}

            <h3>Статус</h3>
            <StatusActions key={`s-${c.id}-${c.status}`} card={c} busy={busy} run={run} />

            {ASSIGNERS.includes(role) && !closed && (
              <>
                <h3>Назначение</h3>
                <AssignForm key={`a-${c.id}-${c.updated_at}`} card={c} busy={busy} run={run} />
              </>
            )}

            <h3>Комментарии</h3>
            <Comments card={c} canWrite={COMMENTERS.includes(role)} busy={busy} run={run} />

            <h3>История статусов</h3>
            {c.history.length === 0 ? (
              <p className="muted">Изменений пока нет.</p>
            ) : (
              <ul className="timeline">
                {c.history.map((h) => (
                  <li key={h.id}>
                    <div className="when">
                      {fmtDateTime(h.created_at)} · {h.changed_by ?? 'система'}
                    </div>
                    {h.from_status ? `${STATUS_LABELS[h.from_status]} → ` : ''}
                    {STATUS_LABELS[h.to_status]}
                    {h.comment ? `: ${h.comment}` : ''}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </aside>
    </>
  )
}
