import { STATUS_LABELS, type CaseStatus } from './caseTypes'
import './cases.css'

export default function StatusBadge({ status }: { status: CaseStatus }) {
  return <span className={`st st-${status}`}>{STATUS_LABELS[status]}</span>
}
