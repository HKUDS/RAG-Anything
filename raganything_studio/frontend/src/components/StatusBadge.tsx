import type { JobStatus } from '../types/studio'

interface StatusBadgeProps {
  status: JobStatus | string
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return <span className={`status status-${status}`}>{statusLabel(status)}</span>
}

function statusLabel(status: string) {
  if (status === 'indexed') return 'completed'
  if (status === 'uploaded') return 'pending'
  return status
}
