import { useState, type FormEvent } from 'react'
import { useAuth } from './auth'
import './public.css'

/** Вход и регистрация граждан. Сотрудники входят на главной странице. */
export default function AccountPage() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (mode === 'register' && password !== repeat) {
      setError('Пароли не совпадают')
      return
    }
    setBusy(true)
    try {
      if (mode === 'login') await login(email.trim(), password)
      else await register(email.trim(), password, name.trim())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось выполнить запрос')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="public-shell">
      <header className="public-head">
        <strong>Обращения граждан · Уфа</strong>
        <span>
          <a href="#/public">Подать обращение без входа</a> · <a href="#/">Для сотрудников</a>
        </span>
      </header>
      <form className="card public-form account-form" onSubmit={submit}>
        <h2>{mode === 'login' ? 'Вход в личный кабинет' : 'Регистрация'}</h2>
        <label>
          Электронная почта
          <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        {mode === 'register' && (
          <label>
            Имя (необязательно)
            <input value={name} maxLength={200} autoComplete="name" onChange={(e) => setName(e.target.value)} />
          </label>
        )}
        <label>
          Пароль
          <input
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {mode === 'register' && (
          <>
            <span className="muted">Не короче 8 символов, обязательно буквы и цифры.</span>
            <label>
              Повторите пароль
              <input type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required />
            </label>
          </>
        )}
        {error && <p className="error">{error}</p>}
        <div className="account-actions">
          <button type="submit" disabled={busy || !email || !password}>
            {busy ? 'Подождите…' : mode === 'login' ? 'Войти' : 'Зарегистрироваться'}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login')
              setError(null)
            }}
          >
            {mode === 'login' ? 'Создать аккаунт' : 'У меня уже есть аккаунт'}
          </button>
        </div>
      </form>
    </div>
  )
}
