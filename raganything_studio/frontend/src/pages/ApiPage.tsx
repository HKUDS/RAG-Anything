import { BookOpen, Code2, ExternalLink, FileJson } from 'lucide-react'

export default function ApiPage() {
  return (
    <section className="page api-page">
      <div className="api-docs-header">
        <div>
          <h1>API Reference</h1>
          <p>FastAPI-generated OpenAPI documentation for the local Studio server.</p>
        </div>
        <div className="actions">
          <a className="button" href="/openapi.json" target="_blank" rel="noreferrer">
            <FileJson size={16} />
            OpenAPI JSON
          </a>
          <a className="button" href="/redoc" target="_blank" rel="noreferrer">
            <BookOpen size={16} />
            ReDoc
          </a>
          <a className="button primary" href="/docs" target="_blank" rel="noreferrer">
            <ExternalLink size={16} />
            Swagger UI
          </a>
        </div>
      </div>

      <div className="api-docs-frame-shell">
        <div className="api-docs-frame-toolbar">
          <span><Code2 size={15} /> /docs</span>
          <a href="/docs" target="_blank" rel="noreferrer">Open in new tab</a>
        </div>
        <iframe className="api-docs-frame" src="/docs" title="RAG-Anything Studio API docs" />
      </div>
    </section>
  )
}
