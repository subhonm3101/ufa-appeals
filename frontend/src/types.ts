// Форматы ответов бэкенда, которые использует дашборд

export interface Category {
  code: string
  name: string
}

export interface District {
  id: number
  name: string
}

export interface CategoryStat {
  code: string
  name: string
  count: number
  prev_count: number
  change_pct: number | null
  share: number
}

export interface Summary {
  date_from: string
  date_to: string
  prev_date_from: string
  prev_date_to: string
  days: number
  total: number
  prev_total: number
  change_pct: number | null
  per_day: number
  uncategorized: number
  by_category: CategoryStat[]
}

export interface TimeseriesPoint {
  period: string
  count: number
}

export interface Timeseries {
  date_from: string
  date_to: string
  granularity: string
  total: number
  points: TimeseriesPoint[]
}

export interface ForecastItem {
  target_date: string
  value: number
  lower: number
  upper: number
}

export interface Forecast {
  granularity: 'day' | 'week'
  level: 'city' | 'category' | 'district'
  model: {
    name: string
    version: string
    metrics: Record<string, unknown>
    made_at: string
  }
  items: ForecastItem[]
}

export interface AnomalyItem {
  category: string | null
  category_name: string | null
  district: string | null
  start: string
  end: string
  days: number
  peak: number
  expected: number
  score: number
}

export interface AnomalyPage {
  items: AnomalyItem[]
  total: number
}
