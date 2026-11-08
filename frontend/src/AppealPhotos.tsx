import { useEffect, useState } from 'react'
import { getToken } from './api'
import { useFetch } from './useFetch'
import './photos.css'

interface Attachment {
  id: number
  name: string
  content_type: string
  size_bytes: number
}

/** Фотографии из обращения: файлы защищены, поэтому грузим их с токеном и показываем из памяти. */
export default function AppealPhotos({ appealId }: { appealId: number }) {
  const list = useFetch<Attachment[]>(`/api/appeals/${appealId}/attachments`)
  const [urls, setUrls] = useState<Record<number, string>>({})
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const items = list.data ?? []
    let cancelled = false
    const created: string[] = []
    setUrls({})
    setFailed(false)
    for (const a of items) {
      const token = getToken()
      fetch(`/api/attachments/${a.id}/file`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
        .then((r) => {
          if (!r.ok) throw new Error(String(r.status))
          return r.blob()
        })
        .then((blob) => {
          const url = URL.createObjectURL(blob)
          created.push(url)
          if (cancelled) URL.revokeObjectURL(url)
          else setUrls((u) => ({ ...u, [a.id]: url }))
        })
        .catch(() => {
          if (!cancelled) setFailed(true)
        })
    }
    return () => {
      cancelled = true
      created.forEach((u) => URL.revokeObjectURL(u))
    }
  }, [list.data])

  const items = list.data ?? []
  if (list.error || items.length === 0) return null

  return (
    <>
      <h3>Фотографии</h3>
      <div className="photo-grid">
        {items.map((a) =>
          urls[a.id] ? (
            <a key={a.id} href={urls[a.id]} target="_blank" rel="noreferrer" title={a.name}>
              <img src={urls[a.id]} alt={a.name} />
            </a>
          ) : (
            <div key={a.id} className="photo-placeholder muted">
              Загрузка…
            </div>
          ),
        )}
      </div>
      {failed && <p className="error">Не удалось загрузить часть фотографий.</p>}
    </>
  )
}
