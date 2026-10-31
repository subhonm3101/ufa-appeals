import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { ApiError, apiFetch, getToken, login as apiLogin, setToken, type User } from './api'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState<boolean>(() => getToken() !== null)

  // при загрузке страницы проверяем сохранённый токен
  useEffect(() => {
    if (!getToken()) return
    let cancelled = false
    apiFetch<User>('/api/auth/me')
      .then((u) => {
        if (!cancelled) setUser(u)
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) setToken(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // любой запрос с истёкшим токеном возвращает на страницу входа
  useEffect(() => {
    const onExpired = () => setUser(null)
    window.addEventListener('auth-expired', onExpired)
    return () => window.removeEventListener('auth-expired', onExpired)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const res = await apiLogin(email, password)
    setToken(res.access_token)
    setUser(res.user)
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth нужно вызывать внутри AuthProvider')
  return ctx
}
