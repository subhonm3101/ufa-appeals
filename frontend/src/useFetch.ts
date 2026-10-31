import { useEffect, useState } from 'react'
import { apiFetch } from './api'

export interface FetchState<T> {
  data: T | null
  error: string | null
  loading: boolean
}

/** GET-запрос с отменой устаревших ответов. path = null отключает запрос. */
export function useFetch<T>(path: string | null): FetchState<T> {
  const [state, setState] = useState<FetchState<T>>({
    data: null,
    error: null,
    loading: path !== null,
  })

  useEffect(() => {
    if (path === null) {
      setState({ data: null, error: null, loading: false })
      return
    }
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    apiFetch<T>(path)
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false })
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          const message = e instanceof Error ? e.message : 'Ошибка запроса'
          setState({ data: null, error: message, loading: false })
        }
      })
    return () => {
      cancelled = true
    }
  }, [path])

  return state
}
