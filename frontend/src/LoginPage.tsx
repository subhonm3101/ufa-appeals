import { useState, type FormEvent } from 'react'
import { useAuth } from './auth'

export default function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email.trim(), password)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Не удалось войти')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="center">
      <form className="card login" onSubmit={onSubmit}>
        <h1>Анализ обращений граждан</h1>
        <p className="muted">Вход для сотрудников. Город: Уфа.</p>

        <label>
          Электронная почта
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
          />
        </label>

        <label>
          Пароль
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>

        {error && (
          <div className="alert" role="alert">
            {error}
          </div>
        )}

        <button type="submit" disabled={busy || !email || !password}>
          {busy ? 'Входим…' : 'Войти'}
        </button>
      </form>
    </main>
  )
}
