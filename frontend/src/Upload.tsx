import { useRef, useState } from 'react'
import { apiFetch, ApiError } from './api'
import './dashboard.css'
import './upload.css'

interface RowError {
  row: number
  message: string
}

interface ImportReport {
  filename: string
  dry_run: boolean
  batch_id: number | null
  rows_total: number
  rows_failed: number
  duplicates_skipped: number
  new_rows: number
  inserted: number
  errors: RowError[]
  errors_truncated: boolean
}

export default function Upload() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<ImportReport | null>(null)

  async function send(dryRun: boolean) {
    if (!file) return
    setBusy(true)
    setError(null)
    setReport(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const data = await apiFetch<ImportReport>(`/api/import?dry_run=${dryRun}`, {
        method: 'POST',
        body: form,
      })
      setReport(data)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось выполнить запрос')
    } finally {
      setBusy(false)
    }
  }

  function pick(f: File | null) {
    setFile(f)
    setReport(null)
    setError(null)
  }

  const canLoad = report?.dry_run === true && report.new_rows > 0 && !busy

  return (
    <div className="stack">
      <div className="card">
        <p className="muted note">
          Файл .csv или .xlsx, не более заданного размера. Сначала нажмите «Проверить»: в базу
          ничего не запишется, вы увидите отчёт. Если всё устраивает, нажмите «Загрузить».
        </p>
        <div className="upload-row">
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => pick(e.target.files?.[0] ?? null)}
          />
          <button className="secondary" disabled={!file || busy} onClick={() => send(true)}>
            Проверить
          </button>
          <button disabled={!canLoad} onClick={() => send(false)}>
            Загрузить
          </button>
        </div>
        {busy && <p className="muted note">Выполняется…</p>}
        {error && <p className="error">{error}</p>}
      </div>

      {report && (
        <div className="card">
          <div className="block-head">
            <h2>
              {report.dry_run ? 'Результат проверки' : 'Результат загрузки'}: {report.filename}
            </h2>
          </div>
          <div className="kpis">
            <div className="kpi">
              <span className="muted">Строк в файле</span>
              <strong>{report.rows_total}</strong>
            </div>
            <div className="kpi">
              <span className="muted">{report.dry_run ? 'Будет добавлено' : 'Добавлено'}</span>
              <strong>{report.dry_run ? report.new_rows : report.inserted}</strong>
            </div>
            <div className="kpi">
              <span className="muted">Дубликаты (пропущены)</span>
              <strong>{report.duplicates_skipped}</strong>
            </div>
            <div className="kpi">
              <span className="muted">Строки с ошибками</span>
              <strong>{report.rows_failed}</strong>
            </div>
          </div>
          {report.dry_run && report.new_rows === 0 && (
            <p className="muted note">Новых корректных строк нет, загружать нечего.</p>
          )}
          {!report.dry_run && (
            <p className="muted note">Данные записаны в базу (пакет №{report.batch_id}).</p>
          )}

          {report.errors.length > 0 && (
            <>
              <h3>Ошибки в строках</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Строка</th>
                      <th>Что не так</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.errors.map((er, i) => (
                      <tr key={i}>
                        <td>{er.row}</td>
                        <td style={{ whiteSpace: 'normal' }}>{er.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {report.errors_truncated && (
                <p className="muted note">Показаны первые 50 ошибок.</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
