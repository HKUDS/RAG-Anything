import type { JobStatus } from '../types/studio'

interface StatusBadgeProps {
  status: JobStatus | string
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return <span className={`status status-${status}`}>{status}</span>
}

