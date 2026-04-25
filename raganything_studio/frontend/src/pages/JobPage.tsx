import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, ChevronDown, ChevronUp, Circle, Loader2, MessageSquare, XCircle } from 'lucide-react'
import { getJob } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'

const PIPELINE_STAGES = [
  { key: 'queued', label: 'Queued', detail: 'Job accepted' },
  { key: 'preparing', label: 'Prepare', detail: 'Load settings and files' },
  { key: 'parsing', label: 'Parse', detail: 'Extract content list' },
  { key: 'building_index', label: 'Index', detail: 'Insert text and vectors' },
  { key: 'finalizing', label: 'Finalize', detail: 'Persist results' },
  { key: 'done', label: 'Done', detail: 'Ready for query' },
]

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
  const stageIndex = PIPELINE_STAGES.findIndex((stage) => stage.key === job.stage)
  const completedIndex = job.status === 'succeeded'
    ? PIPELINE_STAGES.length - 1
    : Math.max(stageIndex, 0)
  const logStats = summarizeLogs(job.logs)

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

      <div className="job-overview">
        <div className="panel stack job-progress-panel">
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

        <div className="panel stack job-signal-panel">
          <h2>Processing Signals</h2>
          <div className="signal-grid">
            <Signal label="Log lines" value={String(job.logs.length)} />
            <Signal label="Content blocks" value={logStats.blocks ?? '—'} />
            <Signal label="Modal items" value={logStats.modalItems ?? '—'} />
            <Signal label="Last update" value={new Date(job.updated_at).toLocaleTimeString()} />
          </div>
        </div>
      </div>

      <div className="pipeline-strip">
        {PIPELINE_STAGES.map((stage, index) => {
          const isActive = stage.key === job.stage
          const isDone = job.status === 'succeeded' || index < completedIndex
          const isFailed = job.status === 'failed' && isActive
          return (
            <div className={`pipeline-step ${isActive ? 'active' : ''} ${isDone ? 'done' : ''} ${isFailed ? 'failed' : ''}`} key={stage.key}>
              <span className="pipeline-icon">
                {isFailed ? <XCircle size={18} />
                  : isDone ? <CheckCircle2 size={18} />
                    : isActive ? <Loader2 size={18} className="spin" />
                      : <Circle size={18} />}
              </span>
              <strong>{stage.label}</strong>
              <small>{stage.detail}</small>
            </div>
          )
        })}
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

function Signal({ label, value }: { label: string; value: string }) {
  return (
    <div className="signal-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function summarizeLogs(logs: string[]): { blocks?: string; modalItems?: string } {
  const joined = logs.join('\n')
  const blocksMatch = joined.match(/(\d+)\s+content blocks/i)
  const modalMatch = joined.match(/Processing\s+(\d+)\s+multimodal items/i)
  return {
    blocks: blocksMatch?.[1],
    modalItems: modalMatch?.[1],
  }
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
