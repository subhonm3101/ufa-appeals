// Обращения к бэкенду. Адреса /api/... проходят через прокси Vite (vite.config.ts).

const TOKEN_KEY = 'appeals_token'

export type Role = 'operator' | 'analyst' | 'manager' | 'admin' | 'executor' | 'citizen'

export const ROLE_LABELS: Record<Role, string> = {
  operator: 'Оператор',
  analyst: 'Аналитик',
  manager: 'Руководитель',
  admin: 'Администратор',
  executor: 'Исполнитель',
  citizen: 'Гражданин',
}

export interface User {
  id: number
  email: string
  full_name: string | null
  role: Role
  is_active: boolean
  last_login_at: string | null
  created_at: string
  department_id?: number | null
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

/** Скачивает файл с авторизацией (имя берётся из заголовка Content-Disposition). */
export async function downloadFile(path: string): Promise<void> {
  const token = getToken()
  const res = await request(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (res.status === 401 && token) {
    setToken(null)
    window.dispatchEvent(new Event('auth-expired'))
  }
  if (!res.ok) throw await readError(res)
  const blob = await res.blob()
  const match = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = match?.[1] ?? 'report.xlsx'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}


export async function registerCitizen(email: string, password: string, fullName: string): Promise<TokenResponse> {
  const res = await request('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, full_name: fullName || null }),
  })
  if (!res.ok) throw await readError(res)
  return (await res.json()) as TokenResponse
}
