// Типы и подписи рабочего процесса обращений (ответы /api/cases и /api/appeals/{id})

export type CaseStatus = 'new' | 'accepted' | 'in_progress' | 'waiting' | 'resolved' | 'rejected'

export const STATUS_ORDER: CaseStatus[] = [
  'new',
  'accepted',
  'in_progress',
  'waiting',
  'resolved',
  'rejected',
]

export const STATUS_LABELS: Record<CaseStatus, string> = {
  new: 'Новое',
  accepted: 'Принято',
  in_progress: 'В работе',
  waiting: 'Ожидает ответа',
  resolved: 'Решено',
  rejected: 'Отклонено',
}

export const SOURCE_LABELS: Record<string, string> = {
  import: 'Импорт файла',
  web: 'Сайт',
  operator: 'Оператор',
  api: 'Внешний API',
}

export const CLOSED: CaseStatus[] = ['resolved', 'rejected']

export interface CaseItem {
  id: number
  public_number: string
  excerpt: string
  created_at: string
  status: CaseStatus
  category: string | null
  category_name: string | null
  district: string | null
  department_name: string | null
  assignee_id: number | null
  assignee_email: string | null
  assignee_name: string | null
  due_at: string | null
  is_overdue: boolean
  needs_review: boolean
}

export interface CasePage {
  total: number
  limit: number
  offset: number
  status_counts: Record<CaseStatus, number>
  review_count: number
  items: CaseItem[]
}

export interface HistoryEntry {
  id: number
  from_status: CaseStatus | null
  to_status: CaseStatus
  comment: string | null
  created_at: string
  changed_by: string | null
}

export interface CommentEntry {
  id: number
  body: string
  is_internal: boolean
  created_at: string
  author: string | null
}

export interface Suggestion {
  category: string
  category_name: string
  confidence: number
  urgency: number | null
}

export interface CaseCard {
  id: number
  public_number: string
  external_id: string | null
  text: string
  created_at: string
  status: CaseStatus
  source: string
  address_text: string | null
  contact_email: string | null
  category: string | null
  category_name: string | null
  district: string | null
  department_id: number | null
  department_name: string | null
  assignee_id: number | null
  assignee_email: string | null
  assignee_name: string | null
  due_at: string | null
  resolved_at: string | null
  response_text: string | null
  updated_at: string
  is_overdue: boolean
  needs_review: boolean
  suggestion: Suggestion | null
  allowed_transitions: CaseStatus[]
  history: HistoryEntry[]
  comments: CommentEntry[]
}

export interface Department {
  id: number
  name: string
}

export interface Executor {
  id: number
  email: string
  full_name: string | null
  department_id: number | null
}

export function fmtDateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

export function personName(name: string | null, email: string | null): string {
  return name || email || '—'
}
