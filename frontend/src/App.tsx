import { useState } from 'react'
import { ROLE_LABELS, type Role } from './api'
import { useAuth } from './auth'
import LoginPage from './LoginPage'

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
    roles: ['operator', 'analyst', 'manager', 'admin'],
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

  if (loading) return <div className="center muted">Загрузка…</div>
  if (!user) return <LoginPage />

  const available = PAGES.filter((p) => p.roles.includes(user.role))
  const current = available.find((p) => p.id === page) ?? available[0]

  return (
    <div className="shell">
      <header className="topbar">
        <strong>Анализ обращений граждан · Уфа</strong>
        <span className="spacer" />
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
        <div className="card">
          <p className="muted">{current.hint}</p>
        </div>
      </main>
    </div>
  )
}
