import { FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, FilePlus2, Send, Settings } from 'lucide-react'
import { submitQuery } from '../api/client'
import { useReadiness } from '../context/readiness'

export default function QueryPage() {
  const { fullyConfigured, indexedCount, isLoading: readinessLoading } = useReadiness()
  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [useMultimodal, setUseMultimodal] = useState(true)

  const queryMutation = useMutation({
    mutationFn: () => submitQuery(question, mode, useMultimodal),
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    queryMutation.mutate()
  }

  const notReady = !readinessLoading && (!fullyConfigured || indexedCount === 0)

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Query Console</h1>
          <p>Ask the indexed multimodal knowledge base</p>
        </div>
        {!readinessLoading && indexedCount > 0 && (
          <span className="indexed-badge">
            {indexedCount} indexed {indexedCount === 1 ? 'document' : 'documents'}
          </span>
        )}
      </div>

      {!readinessLoading && !fullyConfigured && (
        <div className="gate-banner">
          <AlertTriangle size={20} className="gate-banner__icon" />
          <div className="gate-banner__body">
            <strong>API keys not configured</strong>
            <p>LLM and Embedding keys are required to query the knowledge base.</p>
          </div>
          <Link className="button primary" to="/settings">
            <Settings size={16} />
            Go to Settings
          </Link>
        </div>
      )}

      {!readinessLoading && fullyConfigured && indexedCount === 0 && (
        <div className="gate-banner gate-banner--info">
          <FilePlus2 size={20} className="gate-banner__icon" />
          <div className="gate-banner__body">
            <strong>No indexed documents yet</strong>
            <p>Upload and process at least one document before querying.</p>
          </div>
          <Link className="button primary" to="/documents/new">
            <FilePlus2 size={16} />
            Upload Document
          </Link>
        </div>
      )}

      <div className="split" style={notReady ? { opacity: 0.45, pointerEvents: 'none' } : undefined}>
        <form className="panel stack" onSubmit={handleSubmit}>
          <label>
            Question
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={8}
              placeholder="Ask anything about your indexed documents…"
            />
          </label>
          <label>
            Mode
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="naive">naive</option>
              <option value="local">local</option>
              <option value="global">global</option>
              <option value="hybrid">hybrid</option>
              <option value="mix">mix</option>
            </select>
          </label>
          <label className="inline-check">
            <input
              checked={useMultimodal}
              type="checkbox"
              onChange={(e) => setUseMultimodal(e.target.checked)}
            />
            Use multimodal query enhancement
          </label>
          {queryMutation.error ? <div className="error-panel">{queryMutation.error.message}</div> : null}
          <button className="button primary" disabled={!question.trim() || queryMutation.isPending || notReady}>
            <Send size={18} />
            {queryMutation.isPending ? 'Querying…' : 'Submit'}
          </button>
        </form>

        <div className="panel stack">
          <h2>Answer</h2>
          <div className="answer">
            {queryMutation.isPending
              ? <span className="answer--pending">Thinking…</span>
              : queryMutation.data?.answer
                ? queryMutation.data.answer
                : <span className="answer--empty">No answer yet</span>}
          </div>
          <h2>Sources</h2>
          <div className="empty">
            {queryMutation.data?.sources.length
              ? `${queryMutation.data.sources.length} source(s) returned`
              : 'No sources returned'}
          </div>
          {queryMutation.data?.raw ? (
            <details>
              <summary>Raw result</summary>
              <pre className="json-view">{JSON.stringify(queryMutation.data.raw, null, 2)}</pre>
            </details>
          ) : null}
        </div>
      </div>
    </section>
  )
}
