import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Eye, FilePlus2 } from 'lucide-react'
import { getDocuments } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'

export default function DocumentsPage() {
  const { data: documents = [], isLoading, error } = useQuery({
    queryKey: ['documents'],
    queryFn: getDocuments,
  })

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Documents</h1>
          <p>Uploaded files and processing state</p>
        </div>
        <Link className="button primary" to="/documents/new">
          <FilePlus2 size={18} />
          Upload
        </Link>
      </div>

      {error ? <div className="error-panel">{(error as Error).message}</div> : null}
      {isLoading ? <div className="empty">Loading documents</div> : null}

      <div className="table">
        <div className="table-row table-head">
          <span>Filename</span>
          <span>Status</span>
          <span>Created</span>
          <span></span>
        </div>
        {documents.map((document) => (
          <div className="table-row" key={document.id}>
            <span>{document.filename}</span>
            <StatusBadge status={document.status} />
            <span>{new Date(document.created_at).toLocaleString()}</span>
            <Link className="icon-button" to="/query" title="Query">
              <Eye size={17} />
            </Link>
          </div>
        ))}
      </div>
      {!isLoading && documents.length === 0 ? <div className="empty">No documents yet</div> : null}
    </section>
  )
}

