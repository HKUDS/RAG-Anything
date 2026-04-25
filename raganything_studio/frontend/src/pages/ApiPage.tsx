import { Code2, ServerCog } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function ApiPage() {
  return (
    <section className="page api-page">
      <div className="panel stack api-panel">
        <div className="panel-header-row">
          <h1>API</h1>
          <Code2 size={20} />
        </div>
        <p>Studio serves local REST endpoints under <code>/api</code>.</p>
        <div className="api-endpoint-list">
          <Endpoint method="GET" path="/api/documents" />
          <Endpoint method="POST" path="/api/documents/upload" />
          <Endpoint method="POST" path="/api/documents/{id}/process" />
          <Endpoint method="POST" path="/api/query" />
          <Endpoint method="GET" path="/api/settings" />
        </div>
        <Link className="button" to="/settings">
          <ServerCog size={16} />
          Provider Settings
        </Link>
      </div>
    </section>
  )
}

function Endpoint({ method, path }: { method: string; path: string }) {
  return (
    <div className="api-endpoint">
      <span>{method}</span>
      <code>{path}</code>
    </div>
  )
}
