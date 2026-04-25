import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, FileText, MessageSquare, Rows3 } from 'lucide-react'
import { getDocumentContentList, getDocuments } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'

export default function DocumentResultPage() {
  const { documentId = '' } = useParams()
  const { data: documents = [] } = useQuery({
    queryKey: ['documents'],
    queryFn: getDocuments,
  })
  const { data, error, isLoading } = useQuery({
    queryKey: ['document-content-list', documentId],
    queryFn: () => getDocumentContentList(documentId),
    enabled: Boolean(documentId),
  })
  const document = documents.find((item) => item.id === documentId)
  const items = data?.items ?? []
  const typeCounts = countTypes(items)

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <Link className="link-subtle" to="/documents">
            <ArrowLeft size={14} /> Documents
          </Link>
          <h1>Processing Result</h1>
          <p>{document?.filename ?? documentId}</p>
        </div>
        <div className="actions">
          {document ? <StatusBadge status={document.status} /> : null}
          <Link className="button primary" to="/query">
            <MessageSquare size={17} />
            Query
          </Link>
        </div>
      </div>

      {error ? <div className="error-panel">{(error as Error).message}</div> : null}
      {isLoading ? <div className="empty">Loading result…</div> : null}

      <div className="rag-stat-row result-stat-row">
        <ResultStat label="Chunks" value={String(document?.chunks_count ?? '—')} />
        <ResultStat label="Items" value={String(items.length)} />
        <ResultStat label="Text" value={String(typeCounts.text ?? 0)} />
        <ResultStat label="Visual" value={String((typeCounts.image ?? 0) + (typeCounts.table ?? 0))} />
      </div>

      <div className="panel stack">
        <div className="panel-header-row">
          <h2>Parsed Content</h2>
          <span className="mode-pill">{document?.status_detail ?? 'result'}</span>
        </div>
        {items.length > 0 ? (
          <div className="result-item-list">
            {items.slice(0, 200).map((item, index) => (
              <ResultItem key={`${index}-${String(item.type ?? 'item')}`} item={item} index={index} />
            ))}
          </div>
        ) : (
          <div className="empty">No parser content preview was found for this document.</div>
        )}
      </div>
    </section>
  )
}

function ResultStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rag-stat">
      <Rows3 size={17} />
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function ResultItem({ item, index }: { item: Record<string, unknown>; index: number }) {
  const type = String(item.type ?? item.label ?? 'item')
  const page = typeof item.page_idx === 'number' ? Number(item.page_idx) + 1 : null
  const text = String(item.text ?? item.table_body ?? item.caption ?? '').trim()

  return (
    <article className="result-item">
      <div className="result-item__meta">
        <FileText size={14} />
        <strong>{type}</strong>
        {page != null ? <span>p. {page}</span> : null}
        <span>#{index + 1}</span>
      </div>
      <p>{text || 'No text preview available'}</p>
    </article>
  )
}

function countTypes(items: Array<Record<string, unknown>>) {
  return items.reduce<Record<string, number>>((counts, item) => {
    const type = String(item.type ?? 'item')
    return { ...counts, [type]: (counts[type] ?? 0) + 1 }
  }, {})
}
