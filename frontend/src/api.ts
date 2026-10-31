// Обращения к бэкенду. Адреса /api/... проходят через прокси Vite (vite.config.ts).

const TOKEN_KEY = 'appeals_token'

export type Role = 'operator' | 'analyst' | 'manager' | 'admin'

export const ROLE_LABELS: Record<Role, string> = {
  operator: 'Оператор',
  analyst: 'Аналитик',
  manager: 'Руководитель',
  admin: 'Администратор',
}

export interface User {
  id: number
  email: string
  full_name: string | null
  role: Role
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

interface TokenResponse {
  access_token: string
  expires_in: number
  user: User
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* хранилище недоступно: вход будет действовать до перезагрузки страницы */
  }
}

async function readError(res: Response): Promise<ApiError> {
  let message = `Ошибка ${res.status}`
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') message = body.detail
  } catch {
    /* тело ответа пустое или не JSON */
  }
  return new ApiError(res.status, message)
}

async function request(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(path, init)
  } catch {
    throw new ApiError(0, 'Сервер недоступен. Проверьте, что бэкенд запущен.')
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await request(path, { ...init, headers })
  if (res.status === 401 && token) {
    // токен истёк или пользователь отключён: возвращаем на страницу входа
    setToken(null)
    window.dispatchEvent(new Event('auth-expired'))
  }
  if (!res.ok) throw await readError(res)
  return (await res.json()) as T
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const body = new URLSearchParams({ username: email, password })
  const res = await request('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (res.status === 401) throw new ApiError(401, 'Неверная почта или пароль')
  if (!res.ok) throw await readError(res)
  return (await res.json()) as TokenResponse
}
