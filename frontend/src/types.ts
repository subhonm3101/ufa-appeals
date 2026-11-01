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

export interface PriorityFactors {
  raw: Record<string, unknown>
  as_of: string
  method: string
  weights: Record<string, number>
  components: Record<string, number>
}

export interface QueueItem {
  cluster_id: number
  score: number
  factors: PriorityFactors
  as_of: string
  calculated_at: string
  status: string | null
  appeals_count: number
  centroid_lat: number | null
  centroid_lon: number | null
  category: string | null
  category_name: string | null
  district: string | null
}

export interface QueuePage {
  items: QueueItem[]
  total: number
  limit: number
  offset: number
  method: string
}

export interface ClusterAppeal {
  id: number
  external_id: string | null
  text: string
  created_at: string
  status: string | null
  lat: number | null
  lon: number | null
}

export interface ClusterDetails {
  id: number
  status: string | null
  appeals_count: number
  centroid_lat: number | null
  centroid_lon: number | null
  first_seen: string | null
  last_seen: string | null
  category: string | null
  category_name: string | null
  district: string | null
  score: number | null
  factors: PriorityFactors | null
  as_of: string | null
  calculated_at: string | null
  components: Record<string, number>
  appeals: ClusterAppeal[]
}
