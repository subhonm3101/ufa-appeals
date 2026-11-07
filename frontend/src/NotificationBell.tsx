import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from './api'
import { fmtDateTime } from './caseTypes'
import { useFetch } from './useFetch'
import './notifications.css'

interface NotificationItem {
  id: number
  appeal_id: number | null
  kind: 'assigned' | 'status_changed' | 'due_soon' | 'overdue'
  message: string
  created_at: string
  read_at: string | null
}

interface Inbox {
  total: number
  unread: number
  items: NotificationItem[]
}

const KIND_LABELS: Record<NotificationItem['kind'], string> = {
  assigned: 'Назначено',
  status_changed: 'Статус',
  due_soon: 'Срок',
  overdue: 'Просрочено',
}

const POLL_MS = 60_000

export default function NotificationBell({ onOpenAppeal }: { onOpenAppeal: (id: number) => void }) {
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [version, setVersion] = useState(0)
  const box = useRef<HTMLDivElement>(null)
  const inbox = useFetch<Inbox>(open ? `/api/notifications?limit=20&v=${version}` : null)

  const loadCount = useCallback(() => {
    apiFetch<{ unread: number }>('/api/notifications/unread-count')
      .then((d) => setUnread(d.unread))
      .catch(() => {
        /* значок просто не обновится; повтор через минуту */
      })
  }, [])

  useEffect(() => {
    loadCount()
    const timer = setInterval(loadCount, POLL_MS)
    return () => clearInterval(timer)
  }, [loadCount])

  useEffect(() => {
    if (inbox.data) setUnread(inbox.data.unread)
  }, [inbox.data])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  async function openItem(n: NotificationItem) {
    try {
      if (!n.read_at) await apiFetch(`/api/notifications/${n.id}/read`, { method: 'POST' })
    } catch {
      /* не удалось отметить прочитанным: карточку всё равно открываем */
    }
    setOpen(false)
    loadCount()
    if (n.appeal_id !== null) onOpenAppeal(n.appeal_id)
  }

  async function readAll() {
    try {
      await apiFetch('/api/notifications/read-all', { method: 'POST' })
    } catch {
      /* ничего: список покажет актуальное состояние */
    }
    setVersion((v) => v + 1)
    loadCount()
  }

  return (
    <div className="bell-box" ref={box}>
      <button
        className="secondary bell"
        aria-label={unread > 0 ? `Уведомления, непрочитанных: ${unread}` : 'Уведомления'}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {unread > 0 && <span className="bell-count">{unread > 99 ? '99+' : unread}</span>}
      </button>

      {open && (
        <div className="bell-panel" role="dialog" aria-label="Уведомления">
          <div className="bell-head">
            <strong>Уведомления</strong>
            <button className="secondary" disabled={unread === 0} onClick={readAll}>
              Прочитать все
            </button>
          </div>
          {inbox.error && <p className="error">{inbox.error}</p>}
          {!inbox.data && !inbox.error && <p className="muted">Загрузка…</p>}
          {inbox.data && inbox.data.items.length === 0 && <p className="muted">Уведомлений нет.</p>}
          <ul className="bell-list">
            {inbox.data?.items.map((n) => (
              <li key={n.id}>
                <button className={n.read_at ? 'bell-item' : 'bell-item unread'} onClick={() => openItem(n)}>
                  <span className={`bell-kind kind-${n.kind}`}>{KIND_LABELS[n.kind]}</span>
                  <span className="bell-text">{n.message}</span>
                  <span className="bell-time">{fmtDateTime(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
