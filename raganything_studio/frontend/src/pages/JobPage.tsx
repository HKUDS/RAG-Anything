import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, MessageSquare } from 'lucide-react'
import { getJob } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'

export default function JobPage() {
  const { jobId = '' } = useParams()
  const logRef = useRef<HTMLPreElement>(null)
  const [errorExpanded, setErrorExpanded] = useState(false)

  const { data: job, error } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => getJob(jobId),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'succeeded' || status === 'failed' || status === 'cancelled' ? false : 1000
    },
  })

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [job?.logs])

  if (error) {
    return (
      <section className="page">
        <div className="error-panel">{(error as Error).message}</div>
      </section>
    )
  }

  if (!job) {
    return (
      <section className="page">
        <div className="empty">Loading job…</div>
      </section>
    )
  }

  const errorSummary = job.error ? extractErrorSummary(job.error) : null

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Job Detail</h1>
          <p className="job-id-label">{job.id}</p>
        </div>
        {job.status === 'succeeded' && (
          <Link className="button primary" to="/query">
            <MessageSquare size={18} />
            Go to Query
          </Link>
        )}
      </div>

      <div className="panel stack">
        <div className="job-topline">
          <StatusBadge status={job.status} />
          <span className="job-stage">{job.stage}</span>
          <strong>{Math.round(job.progress * 100)}%</strong>
        </div>
        <div className="progress">
          <div style={{ width: `${Math.round(job.progress * 100)}%` }} />
        </div>
        <p>{job.message}</p>

        {job.status === 'failed' && errorSummary && (
          <div className="error-summary">
            <div className="error-summary__header">
              <span className="error-summary__label">Error</span>
              <span className="error-summary__text">{errorSummary}</span>
              {job.error && job.error !== errorSummary && (
                <button
                  className="error-summary__toggle"
                  onClick={() => setErrorExpanded((v) => !v)}
                  type="button"
                >
                  {errorExpanded
                    ? <><ChevronUp size={14} /> Hide details</>
                    : <><ChevronDown size={14} /> Show traceback</>}
                </button>
              )}
            </div>
            {errorExpanded && (
              <pre className="error-traceback scroll">{job.error}</pre>
            )}
          </div>
        )}
      </div>

      <div className="log-section">
        <div className="log-section__header">
          <span>Logs</span>
          <span className="log-count">{job.logs.length} lines</span>
        </div>
        <pre className="log-console" ref={logRef}>
          {job.logs.length > 0 ? job.logs.join('\n') : 'Waiting for logs…'}
        </pre>
      </div>
    </section>
  )
}

function extractErrorSummary(error: string): string {
  const lines = error.split('\n').map((l) => l.trim()).filter(Boolean)
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i]
    if (!line.startsWith('File ') && !line.startsWith('^') && line.length > 0) {
      return line.length > 160 ? line.slice(0, 157) + '…' : line
    }
  }
  return lines[lines.length - 1] ?? error
}
