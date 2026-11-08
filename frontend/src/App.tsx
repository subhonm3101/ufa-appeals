import { useEffect, useState } from 'react'
import { ROLE_LABELS, type Role } from './api'
import { useAuth } from './auth'
import Admin from './Admin'
import Appeals from './Appeals'
import Dashboard from './Dashboard'
import PublicPage from './PublicPage'
import LoginPage from './LoginPage'
import NotificationBell from './NotificationBell'
import QueueMap from './QueueMap'
import Upload from './Upload'

type PageId = 'appeals' | 'upload' | 'dashboard' | 'queue' | 'admin'

interface PageDef {
  id: PageId
  title: string
  roles: Role[]
  hint: string
}

// Права совпадают с матрицей ролей на бэкенде (шаг 3.4)
const PAGES: PageDef[] = [
  {
    id: 'appeals',
    title: 'Обращения',
    roles: ['operator', 'analyst', 'manager', 'admin', 'executor'],
    hint: 'Список обращений с фильтрами по району, категории и дате. Появится на шаге 7.2.',
  },
  {
    id: 'upload',
    title: 'Загрузка файлов',
    roles: ['operator', 'admin'],
    hint: 'Загрузка CSV и Excel с проверкой и отчётом об ошибках. Появится на шаге 7.2.',
  },
  {
    id: 'dashboard',
    title: 'Дашборд',
    roles: ['analyst', 'manager', 'admin'],
    hint: 'Динамика обращений, прогноз нагрузки и аномалии. Появится на шаге 7.2.',
  },
  {
    id: 'queue',
    title: 'Очередь и карта',
    roles: ['analyst', 'manager', 'admin'],
    hint: 'Очередь проблем по приоритету, карта Уфы и карточка проблемы. Появится на шаге 7.3.',
  },
  {
    id: 'admin',
    title: 'Пользователи и журнал',
    roles: ['admin'],
    hint: 'Управление пользователями и журнал действий. Появится после шага 7.4.',
  },
]

export default function App() {
  const { user, loading, logout } = useAuth()
  const [page, setPage] = useState<PageId>('appeals')
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onHash = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const [openAppeal, setOpenAppeal] = useState<number | null>(null)

  if (loading) return <div className="center muted">Загрузка…</div>
  if (!user && hash === '#/public') return <PublicPage />
  if (!user)
    return (
      <>
        <LoginPage />
        <a className="public-link" href="#/public">
          Подать обращение или проверить статус
        </a>
      </>
    )

  const available = PAGES.filter((p) => p.roles.includes(user.role))
  const current = available.find((p) => p.id === page) ?? available[0]

  return (
    <div className="shell">
      <header className="topbar">
        <strong>Анализ обращений граждан · Уфа</strong>
        <span className="spacer" />
        <NotificationBell
          onOpenAppeal={(id) => {
            setPage('appeals')
            setOpenAppeal(id)
          }}
        />
        <span className="who">
          {user.full_name || user.email}
          <span className="badge">{ROLE_LABELS[user.role]}</span>
        </span>
        <button className="secondary" onClick={logout}>
          Выйти
        </button>
      </header>

      <nav className="menu" aria-label="Разделы">
        {available.map((p) => (
          <button
            key={p.id}
            className={p.id === current.id ? 'menu-item active' : 'menu-item'}
            onClick={() => setPage(p.id)}
          >
            {p.title}
          </button>
        ))}
      </nav>

      <main className="content">
        <h1>{current.title}</h1>
        {current.id === 'appeals' ? (
          <Appeals openId={openAppeal} onOpenHandled={() => setOpenAppeal(null)} />
        ) : current.id === 'dashboard' ? (
          <Dashboard />
        ) : current.id === 'queue' ? (
          <QueueMap />
        ) : current.id === 'admin' ? (
          <Admin />
        ) : current.id === 'upload' ? (
          <Upload />
        ) : (
          <div className="card">
            <p className="muted">{current.hint}</p>
          </div>
        )}
      </main>
    </div>
  )
}
