import { FormEvent, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, Eraser, FilePlus2, Layers3, MessageSquareText, RotateCcw, Route, Search, Send, Settings } from 'lucide-react'
import { getStudioSettings, submitQuery } from '../api/client'
import { useReadiness } from '../context/readiness'

export default function QueryPage() {
  const { fullyConfigured, indexedCount, isLoading: readinessLoading } = useReadiness()
  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState('global')
  const [topK, setTopK] = useState(40)
  const [chunkTopK, setChunkTopK] = useState(20)
  const [maxEntityTokens, setMaxEntityTokens] = useState(6000)
  const [maxRelationTokens, setMaxRelationTokens] = useState(8000)
  const [maxTotalTokens, setMaxTotalTokens] = useState(30000)
  const [enableRerank, setEnableRerank] = useState(true)
  const [streamResponse, setStreamResponse] = useState(true)
  const [onlyNeedContext, setOnlyNeedContext] = useState(false)
  const [onlyNeedPrompt, setOnlyNeedPrompt] = useState(false)
  const [useMultimodal, setUseMultimodal] = useState(false)
  const [additionalPrompt, setAdditionalPrompt] = useState('')
  const [profileId, setProfileId] = useState<string | null>(null)
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: getStudioSettings })
  const profiles = settings?.profiles ?? []
  const selectedProfileId = profileId ?? settings?.active_profile_id ?? profiles[0]?.id ?? null
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId)

  const queryMutation = useMutation({
    mutationFn: () => submitQuery(
      additionalPrompt.trim()
        ? `${question}\n\nAdditional output instruction: ${additionalPrompt.trim()}`
        : question,
      mode,
      useMultimodal,
      selectedProfileId,
      topK,
    ),
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    queryMutation.mutate()
  }

  function clearQuery() {
    setQuestion('')
    queryMutation.reset()
  }

  const notReady = !readinessLoading && (!fullyConfigured || indexedCount === 0)
  const sourceCount = queryMutation.data?.sources.length ?? 0
  const trace = queryMutation.data?.trace ?? null
  const traceStats = getTraceStats(trace)

  return (
    <section className="retrieval-shell">
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

      <div className="retrieval-layout" style={notReady ? { opacity: 0.45, pointerEvents: 'none' } : undefined}>
        <main className="retrieval-main">
          <div className="retrieval-chat-surface">
            {!queryMutation.data && !queryMutation.isPending ? (
              <div className="retrieval-empty">Start a retrieval by typing your query below</div>
            ) : (
              <div className="retrieval-message-stack">
                <div className="chat-message chat-message--user">{question}</div>
                <div className="chat-message chat-message--assistant">
                  {queryMutation.isPending
                    ? <span className="answer--pending">Retrieving context and composing answer...</span>
                    : queryMutation.data?.answer}
                </div>
                <div className="retrieval-inline-stats">
                  <RagStat icon={<Search size={15} />} label="Mode" value={mode} />
                  <RagStat icon={<Settings size={15} />} label="Profile" value={selectedProfile?.name ?? 'Default'} />
                  <RagStat icon={<Layers3 size={15} />} label="Sources" value={String(sourceCount)} />
                  <RagStat icon={<Route size={15} />} label="Trace" value={String(traceStats.total)} />
                  <RagStat icon={<MessageSquareText size={15} />} label="VLM" value={useMultimodal ? 'On' : 'Off'} />
                </div>
              </div>
            )}
          </div>

          {queryMutation.error ? <div className="error-panel">{queryMutation.error.message}</div> : null}

          <form className="retrieval-input-bar" onSubmit={handleSubmit}>
            <button className="button" type="button" onClick={clearQuery} disabled={queryMutation.isPending}>
              <Eraser size={16} />
              Clear
            </button>
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Enter your query (Support prefix: /<Query Mode>)"
            />
            <button className="button dark-send" disabled={!question.trim() || queryMutation.isPending || notReady}>
              <Send size={17} />
              Send
            </button>
          </form>
        </main>

        <aside className="retrieval-params">
          <h2>Parameters</h2>
          <ParameterText label="Additional Output Prompt" value={additionalPrompt} onChange={setAdditionalPrompt} placeholder="Enter custom prompt (optional)" />
          <label>
            RAG profile
            <select value={selectedProfileId ?? ''} onChange={(e) => setProfileId(e.target.value)}>
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name}</option>
              ))}
            </select>
          </label>
          <ParameterSelect label="Query Mode" value={mode} onChange={setMode} />
          <ParameterNumber label="KG Top K" value={topK} onChange={setTopK} reset={() => setTopK(40)} />
          <ParameterNumber label="Chunk Top K" value={chunkTopK} onChange={setChunkTopK} reset={() => setChunkTopK(20)} />
          <ParameterNumber label="Max Entity Tokens" value={maxEntityTokens} onChange={setMaxEntityTokens} reset={() => setMaxEntityTokens(6000)} />
          <ParameterNumber label="Max Relation Tokens" value={maxRelationTokens} onChange={setMaxRelationTokens} reset={() => setMaxRelationTokens(8000)} />
          <ParameterNumber label="Max Total Tokens" value={maxTotalTokens} onChange={setMaxTotalTokens} reset={() => setMaxTotalTokens(30000)} />
          <ParameterCheck label="Enable Rerank" checked={enableRerank} onChange={setEnableRerank} />
          <ParameterCheck label="Only Need Context" checked={onlyNeedContext} onChange={setOnlyNeedContext} />
          <ParameterCheck label="Only Need Prompt" checked={onlyNeedPrompt} onChange={setOnlyNeedPrompt} />
          <ParameterCheck label="Stream Response" checked={streamResponse} onChange={setStreamResponse} />
          <ParameterCheck label="Multimodal Enhancement" checked={useMultimodal} onChange={setUseMultimodal} />
        </aside>
      </div>
    </section>
  )
}

function RagStat({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="rag-stat">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function ParameterText({
  label, value, placeholder, onChange,
}: {
  label: string
  value: string
  placeholder: string
  onChange: (value: string) => void
}) {
  return (
    <label>
      {label}
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  )
}

function ParameterSelect({
  label, value, onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="naive">Naive</option>
        <option value="local">Local</option>
        <option value="global">Global</option>
        <option value="hybrid">Hybrid</option>
        <option value="mix">Mix</option>
      </select>
    </label>
  )
}

function ParameterNumber({
  label, value, onChange, reset,
}: {
  label: string
  value: number
  onChange: (value: number) => void
  reset: () => void
}) {
  return (
    <label>
      {label}
      <span className="param-control-row">
        <input type="number" value={value} onChange={(event) => onChange(Number(event.target.value))} />
        <button type="button" onClick={reset} title={`Reset ${label}`}>
          <RotateCcw size={13} />
        </button>
      </span>
    </label>
  )
}

function ParameterCheck({
  label, checked, onChange,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="param-check">
      <span>{label}</span>
      <input checked={checked} type="checkbox" onChange={(event) => onChange(event.target.checked)} />
    </label>
  )
}

function getTraceStats(trace: Record<string, unknown> | null) {
  const labels = [
    ['retrieved_text', 'Text'],
    ['retrieved_images', 'Images'],
    ['retrieved_tables', 'Tables'],
    ['retrieved_equations', 'Equations'],
    ['graph_entities', 'Graph'],
  ] as const
  const items = labels.map(([key, label]) => {
    const value = trace?.[key]
    return { label, count: Array.isArray(value) ? value.length : 0 }
  })
  return {
    items,
    total: items.reduce((sum, item) => sum + item.count, 0),
  }
}
