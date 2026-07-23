import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Activity, AlertCircle, BarChart3, Eye, FilePlus2, Loader2, RefreshCw, RotateCcw } from 'lucide-react'
import { getDocuments } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import type { DocumentRecord, DocumentStatus } from '../types/studio'

type StatusFilter = DocumentStatus | 'all'

function docActionLink(doc: DocumentRecord): { to: string; title: string; label: string } | null {
  if (doc.status === 'processing') {
    return doc.latest_job_id ? { to: `/jobs/${doc.latest_job_id}`, title: 'View job progress', label: 'Job' } : null
  }
  if (doc.status === 'failed') {
    return doc.latest_job_id ? { to: `/jobs/${doc.latest_job_id}`, title: 'View error details', label: 'Job' } : null
  }
  if (doc.status === 'indexed' || doc.result_available) {
    return { to: `/documents/${doc.id}/result`, title: 'View processing result', label: 'Result' }
  }
  return null
}

export default function DocumentsPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const { data: documents = [], isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['documents'],
    queryFn: getDocuments,
    refetchInterval: (query) => {
      const hasActive = (query.state.data ?? []).some((d) => d.status === 'processing')
      return hasActive ? 2000 : false
    },
  })
  const counts = useMemo(() => countDocuments(documents), [documents])
  const filteredDocuments = statusFilter === 'all'
    ? documents
    : documents.filter((doc) => doc.status === statusFilter)

  return (
    <section className="documents-workspace">
      <div className="documents-card">
        <div className="documents-card-header">
          <h1>Documents</h1>
        </div>

        <div className="documents-toolbar">
          <div className="documents-toolbar-group">
            <button className="button" type="button" onClick={() => refetch()} disabled={isFetching}>
              <RefreshCw size={16} className={isFetching ? 'spin' : ''} />
              Scan
            </button>
            <button className="button" type="button">
              <Activity size={16} />
              Pipeline Status
            </button>
          </div>
          <div className="documents-toolbar-group">
            <button className="icon-button" type="button" onClick={() => refetch()} disabled={isFetching} title="Refresh">
              <RotateCcw size={16} className={isFetching ? 'spin' : ''} />
            </button>
            <Link className="button primary" to="/documents/new">
              <FilePlus2 size={16} />
              Upload
            </Link>
          </div>
        </div>

        <div className="documents-inner-card">
          <div className="documents-inner-header">
            <h2>Uploaded Documents</h2>
            <div className="status-filter-row">
              <StatusFilterButton active={statusFilter === 'all'} label="All" count={counts.all} onClick={() => setStatusFilter('all')} />
              <StatusFilterButton active={statusFilter === 'indexed'} label="Completed" count={counts.indexed} tone="green" onClick={() => setStatusFilter('indexed')} />
              <StatusFilterButton active={statusFilter === 'processing'} label="Processing" count={counts.processing} tone="blue" onClick={() => setStatusFilter('processing')} />
              <StatusFilterButton active={statusFilter === 'uploaded'} label="Pending" count={counts.uploaded} tone="yellow" onClick={() => setStatusFilter('uploaded')} />
              <StatusFilterButton active={statusFilter === 'failed'} label="Failed" count={counts.failed} tone="red" onClick={() => setStatusFilter('failed')} />
            </div>
          </div>

          {error ? <div className="error-panel">{(error as Error).message}</div> : null}
          {isLoading ? <div className="empty">Loading documents</div> : null}

          <div className="documents-table-wrap">
            <div className="table documents-table">
              <div className="table-row documents-table-row table-head">
                <span>File Name</span>
                <span>Summary</span>
                <span>Status</span>
                <span>Length</span>
                <span>Chunks</span>
                <span>Created</span>
                <span>Updated</span>
                <span></span>
              </div>
              {filteredDocuments.map((doc) => {
                const action = docActionLink(doc)
                return (
                  <div className="table-row documents-table-row" key={doc.id}>
                    <span className="doc-name">
                      <strong>{doc.filename}</strong>
                      <small>{doc.id}</small>
                    </span>
                    <DocumentDetail doc={doc} />
                    <span className="doc-status-cell">
                      <StatusBadge status={doc.status} />
                      {doc.status === 'processing' ? <Loader2 size={13} className="spin doc-spin" /> : null}
                    </span>
                    <span>{doc.content_items_count ?? '-'}</span>
                    <span>{doc.chunks_count ?? '-'}</span>
                    <span>{new Date(doc.created_at).toLocaleString()}</span>
                    <span>{new Date(doc.updated_at).toLocaleString()}</span>
                    {action ? (
                      <Link className="icon-button doc-action-button" to={action.to} title={action.title}>
                        <Eye size={16} />
                      </Link>
                    ) : (
                      <span className="icon-button icon-button--disabled" title="Not available">
                        <Eye size={16} />
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
            {!isLoading && filteredDocuments.length === 0 ? (
              <div className="empty documents-empty">No documents in this status</div>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  )
}

function StatusFilterButton({
  active, label, count, tone = 'neutral', onClick,
}: {
  active: boolean
  label: string
  count: number
  tone?: 'neutral' | 'green' | 'blue' | 'yellow' | 'red'
  onClick: () => void
}) {
  return (
    <button
      className={`status-filter status-filter--${tone} ${active ? 'active' : ''}`}
      onClick={onClick}
      type="button"
    >
      {label} ({count})
    </button>
  )
}

function countDocuments(documents: DocumentRecord[]) {
  return documents.reduce(
    (counts, doc) => ({
      ...counts,
      all: counts.all + 1,
      [doc.status]: counts[doc.status] + 1,
    }),
    {
      all: 0,
      uploaded: 0,
      processing: 0,
      indexed: 0,
      failed: 0,
    } satisfies Record<StatusFilter, number>,
  )
}

function DocumentDetail({ doc }: { doc: DocumentRecord }) {
  if (doc.status === 'processing') {
    const progress = Math.round((doc.latest_job_progress ?? 0) * 100)
    return (
      <span className="doc-detail">
        <span className="doc-detail__line">
          <BarChart3 size={13} />
          {doc.latest_job_stage ?? 'processing'} · {progress}%
        </span>
        <span className="doc-mini-progress"><span style={{ width: `${progress}%` }} /></span>
      </span>
    )
  }

  if (doc.status === 'indexed') {
    const chunks = doc.chunks_count != null ? `${doc.chunks_count} chunks` : null
    const items = doc.content_items_count != null ? `${doc.content_items_count} result items` : null
    return (
      <span className="doc-detail">
        <span className="doc-detail__line">{[chunks, items].filter(Boolean).join(' · ') || 'Ready'}</span>
        <small>{doc.status_detail ?? 'Processing result available'}</small>
      </span>
    )
  }

  if (doc.result_available) {
    return (
      <span className="doc-detail">
        <span className="doc-detail__line">{doc.content_items_count ?? 0} result items</span>
        <small>{doc.status_detail ?? 'Parser result available'}</small>
      </span>
    )
  }

  if (doc.status === 'failed') {
    return (
      <span className="doc-detail doc-detail--failed">
        <span className="doc-detail__line"><AlertCircle size={13} /> Failed</span>
        <small>{doc.status_detail ?? doc.error ?? 'Open job details for traceback'}</small>
      </span>
    )
  }

  return (
    <span className="doc-detail">
      <span className="doc-detail__line">Not processed</span>
      <small>{doc.status_detail ?? 'Upload complete; processing has not started'}</small>
    </span>
  )
}
