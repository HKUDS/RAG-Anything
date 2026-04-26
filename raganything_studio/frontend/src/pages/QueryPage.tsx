import { FormEvent, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Braces,
  Clock,
  Eraser,
  FilePlus2,
  FileText,
  Image as ImageIcon,
  Layers3,
  MessageSquareText,
  Network,
  RotateCcw,
  Route,
  Search,
  Send,
  Settings,
  Table2,
  Trash2,
} from 'lucide-react'
import { getStudioSettings, submitQuery } from '../api/client'
import type { AnswerBlock, MediaItem, QueryResponse, RelationStep, SourceItem } from '../types/studio'
import { useReadiness } from '../context/readiness'

const HISTORY_KEY = 'raganything:queryHistory'
const HISTORY_MAX = 50

interface HistoryEntry {
  id: string
  question: string
  mode: string
  timestamp: number
  response: QueryResponse
}

function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    if (!raw) return []
    return JSON.parse(raw) as HistoryEntry[]
  } catch {
    return []
  }
}

function saveHistory(entries: HistoryEntry[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, HISTORY_MAX)))
  } catch {
    // localStorage quota exceeded — silently ignore
  }
}

function formatTimestamp(ts: number): string {
  const now = Date.now()
  const diff = now - ts
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return new Date(ts).toLocaleDateString()
}

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
  const [streamResponse, setStreamResponse] = useState(false)
  const [onlyNeedContext, setOnlyNeedContext] = useState(false)
  const [onlyNeedPrompt, setOnlyNeedPrompt] = useState(false)
  const [useMultimodal, setUseMultimodal] = useState(false)
  const [additionalPrompt, setAdditionalPrompt] = useState('')
  const [profileId, setProfileId] = useState<string | null>(null)

  const [history, setHistory] = useState<HistoryEntry[]>(loadHistory)
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null)

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
      chunkTopK,
      maxEntityTokens,
      maxRelationTokens,
      maxTotalTokens,
      enableRerank,
      onlyNeedContext,
      onlyNeedPrompt,
      streamResponse,
    ),
    onSuccess: (response) => {
      const entry: HistoryEntry = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        question: question.trim(),
        mode,
        timestamp: Date.now(),
        response,
      }
      setHistory((prev) => {
        const next = [entry, ...prev].slice(0, HISTORY_MAX)
        saveHistory(next)
        return next
      })
      setActiveEntryId(entry.id)
      window.sessionStorage.setItem('raganything:lastQueryTrace', JSON.stringify({
        trace: response.trace ?? null,
        sources: response.sources,
        media: response.media,
        relation_trace: response.relation_trace,
      }))
    },
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setActiveEntryId(null)
    queryMutation.mutate()
  }

  function clearQuery() {
    setQuestion('')
    setActiveEntryId(null)
    queryMutation.reset()
    window.sessionStorage.removeItem('raganything:lastQueryTrace')
  }

  function loadHistoryEntry(entry: HistoryEntry) {
    setQuestion(entry.question)
    setMode(entry.mode)
    setActiveEntryId(entry.id)
    queryMutation.reset()
  }

  function deleteHistoryEntry(id: string) {
    setHistory((prev) => {
      const next = prev.filter((e) => e.id !== id)
      saveHistory(next)
      return next
    })
    if (activeEntryId === id) {
      setActiveEntryId(null)
      queryMutation.reset()
    }
  }

  function clearAllHistory() {
    setHistory([])
    saveHistory([])
    setActiveEntryId(null)
    queryMutation.reset()
  }

  const activeHistoryEntry = activeEntryId ? (history.find((e) => e.id === activeEntryId) ?? null) : null
  const data: QueryResponse | undefined = activeHistoryEntry?.response ?? queryMutation.data
  const displayedQuestion = activeHistoryEntry?.question ?? (queryMutation.data ? question : '')

  const notReady = !readinessLoading && (!fullyConfigured || indexedCount === 0)
  const sourceCount = data?.sources.length ?? 0
  const mediaCount = data?.media.length ?? 0
  const relationCount = data?.relation_trace.length ?? 0
  const traceStats = getTraceStats(data?.trace ?? null)
  const compactResult = shouldUseCompactResult(displayedQuestion || question, data, useMultimodal)
  const visibleSources = compactResult ? (data?.sources ?? []).filter((source) => source.type !== 'equation').slice(0, 3) : data?.sources ?? []
  const visibleMedia = compactResult ? [] : data?.media ?? []
  const visibleRelations = compactResult ? (data?.relation_trace ?? []).slice(0, 4) : data?.relation_trace ?? []

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

      <div className="retrieval-outer">
        <HistorySidebar
          history={history}
          activeId={activeEntryId}
          onSelect={loadHistoryEntry}
          onDelete={deleteHistoryEntry}
          onClearAll={clearAllHistory}
        />

        <div className="retrieval-layout" style={notReady ? { opacity: 0.45, pointerEvents: 'none' } : undefined}>
          <main className="retrieval-main">
            <div className="retrieval-chat-surface">
              {!data && !queryMutation.isPending ? (
                <div className="retrieval-empty">
                  <MessageSquareText size={32} />
                  <p>Start a retrieval by typing your query below</p>
                  {history.length > 0 && (
                    <p className="retrieval-empty-hint">Or select a previous query from the history panel</p>
                  )}
                </div>
              ) : (
                <div className="retrieval-workspace">
                  <div className="query-ribbon">
                    <span>Query</span>
                    <strong>{displayedQuestion}</strong>
                  </div>
                  <div className="retrieval-inline-stats">
                    <RagStat icon={<Search size={15} />} label="Mode" value={activeHistoryEntry?.mode ?? mode} />
                    <RagStat icon={<Settings size={15} />} label="Profile" value={selectedProfile?.name ?? 'Default'} />
                    <RagStat icon={<Layers3 size={15} />} label="Sources" value={String(sourceCount)} />
                    <RagStat icon={<ImageIcon size={15} />} label="Media" value={String(mediaCount)} />
                    <RagStat icon={<Route size={15} />} label="Relations" value={String(relationCount || traceStats.total)} />
                  </div>
                  <div className={`retrieval-result-grid${compactResult ? ' retrieval-result-grid--compact' : ''}`}>
                    <AnswerCanvas
                      answer={data?.answer ?? ''}
                      blocks={data?.answer_blocks ?? []}
                      media={visibleMedia}
                      pending={queryMutation.isPending}
                      compact={compactResult}
                    />
                    <EvidencePanel
                      media={visibleMedia}
                      sources={visibleSources}
                      pending={queryMutation.isPending}
                      compact={compactResult}
                    />
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
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Enter your query (Support prefix: /<Query Mode>)"
              />
              <button className="button dark-send" disabled={!question.trim() || queryMutation.isPending || notReady}>
                <Send size={17} />
                Send
              </button>
            </form>
          </main>

          <aside className="retrieval-params">
            {data ? <RelationTrail steps={visibleRelations} compact={compactResult} /> : null}
            <h2>Parameters</h2>
            <ParameterText label="Additional Output Prompt" value={additionalPrompt} onChange={setAdditionalPrompt} placeholder="Enter custom prompt (optional)" />
            <label>
              RAG profile
              <select value={selectedProfileId ?? ''} onChange={(event) => setProfileId(event.target.value)}>
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
      </div>
    </section>
  )
}

// ── History sidebar ───────────────────────────────────────────────

function HistorySidebar({
  history,
  activeId,
  onSelect,
  onDelete,
  onClearAll,
}: {
  history: HistoryEntry[]
  activeId: string | null
  onSelect: (entry: HistoryEntry) => void
  onDelete: (id: string) => void
  onClearAll: () => void
}) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  return (
    <aside className="query-history-sidebar">
      <div className="query-history-header">
        <Clock size={14} />
        <span>History</span>
        {history.length > 0 && (
          <button
            className="query-history-clear-all"
            onClick={onClearAll}
            title="Clear all history"
          >
            <Trash2 size={12} />
          </button>
        )}
      </div>

      {history.length === 0 ? (
        <div className="query-history-empty">No queries yet</div>
      ) : (
        <ul className="query-history-list">
          {history.map((entry) => (
            <li
              key={entry.id}
              className={`query-history-item${activeId === entry.id ? ' active' : ''}`}
              onMouseEnter={() => setHoveredId(entry.id)}
              onMouseLeave={() => setHoveredId(null)}
            >
              <button
                className="query-history-item__body"
                onClick={() => onSelect(entry)}
                title={entry.question}
              >
                <span className="query-history-item__mode">{entry.mode}</span>
                <span className="query-history-item__question">{entry.question}</span>
                <span className="query-history-item__time">{formatTimestamp(entry.timestamp)}</span>
              </button>
              {hoveredId === entry.id && (
                <button
                  className="query-history-item__delete"
                  onClick={() => onDelete(entry.id)}
                  title="Delete this entry"
                >
                  <Trash2 size={12} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}

// ── Answer + evidence ─────────────────────────────────────────────

function AnswerCanvas({
  answer, blocks, media, pending, compact,
}: {
  answer: string
  blocks: AnswerBlock[]
  media: MediaItem[]
  pending: boolean
  compact: boolean
}) {
  const mediaById = useMemo(() => new Map(media.map((item) => [item.id, item])), [media])
  if (pending) {
    return (
      <section className="answer-canvas">
        <div className="answer--pending">Retrieving multimodal context and composing answer...</div>
      </section>
    )
  }

  const visibleBlocks = (blocks.length > 0 ? blocks : [{ type: 'text', content: answer, source_ids: [], media_ids: [] }])
    .filter((block) => !(compact && block.type === 'media_gallery'))
  return (
    <section className="answer-canvas">
      {visibleBlocks.map((block, index) => (
        <article className={`answer-block answer-block--${block.type}`} key={`${block.type}-${index}`}>
          {block.title ? <h3>{block.title}</h3> : null}
          {block.content ? <p><RichText text={block.content} /></p> : null}
          {block.media_ids.length > 0 ? (
            <div className="answer-media-row">
              {block.media_ids.map((mediaId) => {
                const item = mediaById.get(mediaId)
                if (!item) return null
                return <MediaTile item={item} key={mediaId} />
              })}
            </div>
          ) : null}
        </article>
      ))}
    </section>
  )
}

function EvidencePanel({
  media, sources, pending, compact,
}: {
  media: MediaItem[]
  sources: SourceItem[]
  pending: boolean
  compact: boolean
}) {
  return (
    <aside className="evidence-panel">
      <div className="evidence-panel__header">
        <strong>{compact ? 'Key Evidence' : 'Evidence'}</strong>
        <span>{pending ? '...' : sources.length + media.length}</span>
      </div>
      {media.length > 0 ? (
        <div className="evidence-media-grid">
          {media.slice(0, 4).map((item) => <MediaTile item={item} key={item.id} />)}
        </div>
      ) : null}
      <div className="source-stack">
        {sources.slice(0, 8).map((source, index) => (
          <SourceCard source={source} index={index} key={sourceKey(source, index)} />
        ))}
        {!pending && sources.length === 0 ? <div className="evidence-empty">No structured evidence returned</div> : null}
      </div>
    </aside>
  )
}

function MediaTile({ item }: { item: MediaItem }) {
  return (
    <figure className="media-tile">
      {item.url ? (
        <img src={item.url} alt={item.title ?? 'retrieved visual evidence'} />
      ) : (
        <div className="media-tile__placeholder"><ImageIcon size={22} /></div>
      )}
      <figcaption>
        <strong>{item.title ?? item.type}</strong>
        {item.page_idx != null ? <span>Page {item.page_idx}</span> : null}
      </figcaption>
    </figure>
  )
}

function SourceCard({ source, index }: { source: SourceItem; index: number }) {
  if (source.type === 'equation') {
    return <EquationSourceCard source={source} index={index} />
  }
  const icon = sourceIcon(source.type)
  return (
    <article className="source-card">
      <div className="source-card__top">
        <span className={`source-type source-type--${source.type ?? 'text'}`}>{icon}{source.type ?? 'text'}</span>
        <small>{source.filename ?? `Source ${index + 1}`}</small>
      </div>
      <p>{sanitizeDisplayText(source.preview || 'No preview available')}</p>
      <div className="source-card__meta">
        {source.page_idx != null ? <span>Page {source.page_idx}</span> : null}
        {source.score != null ? <span>{source.score.toFixed(2)}</span> : null}
      </div>
    </article>
  )
}

function EquationSourceCard({ source, index }: { source: SourceItem; index: number }) {
  const equation = getEquationInfo(source)
  return (
    <article className="source-card source-card--equation">
      <div className="source-card__top">
        <span className="source-type source-type--equation"><Braces size={13} />equation</span>
        <small>{source.filename ?? `Source ${index + 1}`}</small>
      </div>
      <div className="equation-card-body">
        {equation.formula ? (
          <div className="equation-display" title={equation.formula}>
            <MathText formula={equation.formula} />
          </div>
        ) : (
          <div className="equation-uncertain" title="The retrieved equation text appears to be damaged or low confidence.">
            Formula transcription unavailable
          </div>
        )}
        {equation.format ? <span className="equation-format">{equation.format}</span> : null}
        <p>{equation.description || sanitizeDisplayText(source.preview || 'No equation description available')}</p>
      </div>
      <div className="source-card__meta">
        {source.page_idx != null ? <span>Page {source.page_idx}</span> : null}
        {source.score != null ? <span>{source.score.toFixed(2)}</span> : null}
      </div>
    </article>
  )
}

function RelationTrail({ steps, compact }: { steps: RelationStep[]; compact: boolean }) {
  if (steps.length === 0) return null
  return (
    <section className="relation-trail">
      <h2>{compact ? 'Trace' : 'Relation Trail'}</h2>
      <div className="relation-step-stack">
        {steps.slice(0, compact ? 4 : 10).map((step) => (
          <article className={`relation-step relation-step--${step.type}`} key={step.id}>
            <span>{relationIcon(step.type)}</span>
            <div>
              <strong>{step.label}</strong>
              {step.description ? <p>{step.description}</p> : null}
            </div>
          </article>
        ))}
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

// ── Pure utilities ────────────────────────────────────────────────

function sourceIcon(type?: string | null) {
  if (type === 'image') return <ImageIcon size={13} />
  if (type === 'table') return <Table2 size={13} />
  if (type === 'equation') return <Braces size={13} />
  return <FileText size={13} />
}

function relationIcon(type: string) {
  if (type === 'relation') return <Route size={13} />
  if (type === 'chunk') return <FileText size={13} />
  return <Network size={13} />
}

function sourceKey(source: SourceItem, index: number) {
  const rawId = source.raw?.id
  return typeof rawId === 'string' ? rawId : `${source.filename ?? 'source'}-${index}`
}

function RichText({ text }: { text: string }) {
  const pieces = text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean)
  return (
    <>
      {pieces.map((piece, index) => {
        if (piece.startsWith('**') && piece.endsWith('**')) {
          return <strong key={`${piece}-${index}`}>{piece.slice(2, -2)}</strong>
        }
        return <span key={`${piece}-${index}`}>{piece}</span>
      })}
    </>
  )
}

function MathText({ formula }: { formula: string }) {
  return <span>{normalizeFormula(formula)}</span>
}

function getEquationInfo(source: SourceItem) {
  const rawEquation = source.raw?.equation
  const equation = isRecord(rawEquation) ? rawEquation : {}
  const formula = typeof equation.formula === 'string' ? equation.formula : extractFormula(source.preview ?? '')
  const description = typeof equation.description === 'string'
    ? equation.description
    : sanitizeEquationDescription(source.preview ?? '')
  const format = typeof equation.format === 'string' ? equation.format : null
  const cleanedFormula = sanitizeDisplayText(formula)
  const cleanedDescription = sanitizeDisplayText(description)
  const uncertain = equation.uncertain === true || isUncertainFormula(cleanedFormula, cleanedDescription)
  return {
    formula: uncertain ? '' : cleanedFormula,
    description: cleanedDescription,
    format: format && isUsefulEquationFormat(format) ? sanitizeDisplayText(format) : null,
  }
}

function extractFormula(text: string) {
  const match = text.match(/(?:LaTeX formula|Equation|公式)\s*[:：]\s*([^]+?)(?:Format|Formula caption|格式|$)/i)
  return match ? sanitizeDisplayText(match[1]) : ''
}

function sanitizeEquationDescription(text: string) {
  return sanitizeDisplayText(text)
    .replace(/Mathematical Equation Analysis:\s*/gi, '')
    .replace(/Equation:\s*.*?(?:Format:|$)/gi, '')
    .replace(/LaTeX formula:\s*.*?(?:Formula caption:|$)/gi, '')
}

function sanitizeDisplayText(text: string) {
  return text.replace(/�/g, ' ').replace(/\s+/g, ' ').trim()
}

function isUncertainFormula(formula: string, description: string) {
  const lowered = `${formula} ${description}`.toLowerCase()
  if (!formula) return true
  if (/[�\uFFFD]/.test(formula)) return true
  if (/(typo|typographical|transcription error|formatting artifact|corrupted|misrendered|misrepresented|does not represent|not represent a mathematically valid)/i.test(lowered)) {
    return true
  }
  const compact = formula.replace(/\s+/g, '')
  if (/^[A-Za-z_]+$/.test(compact) && compact.length <= 8) return true
  if (!/[=+\-*/^\\(){}\[\]|∑∫√≤≥≠≈]/.test(formula) && (formula.match(/[A-Za-z]+/g)?.length ?? 0) > 3) {
    return true
  }
  return false
}

function isUsefulEquationFormat(format: string) {
  const text = sanitizeDisplayText(format)
  if (!text || /^unknown$/i.test(text)) return false
  if (text.length > 36) return false
  if (/(analysis|appears|typo|transcription|artifact)/i.test(text)) return false
  return true
}

function normalizeFormula(formula: string) {
  let text = formula.trim().replace(/^\$+|\$+$/g, '')
  text = text.replace(/\\frac\s*{([^{}]+)}\s*{([^{}]+)}/g, '($1)/($2)')
  const replacements: Array<[RegExp, string]> = [
    [/\\cdot/g, '·'],
    [/\\times/g, '×'],
    [/\\div/g, '÷'],
    [/\\pm/g, '±'],
    [/\\leq?/g, '≤'],
    [/\\geq?/g, '≥'],
    [/\\neq/g, '≠'],
    [/\\approx/g, '≈'],
    [/\\sqrt/g, '√'],
    [/\\alpha/g, 'α'],
    [/\\beta/g, 'β'],
    [/\\gamma/g, 'γ'],
    [/\\delta/g, 'δ'],
    [/\\theta/g, 'θ'],
    [/\\lambda/g, 'λ'],
    [/\\mu/g, 'μ'],
    [/\\pi/g, 'π'],
    [/\\sigma/g, 'σ'],
    [/\\omega/g, 'ω'],
    [/\\Omega/g, 'Ω'],
    [/\\sum/g, '∑'],
    [/\\int/g, '∫'],
  ]
  for (const [pattern, replacement] of replacements) {
    text = text.replace(pattern, replacement)
  }
  return text.replace(/[{}]/g, '').replace(/\s+/g, ' ').trim()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function shouldUseCompactResult(question: string, data: QueryResponse | undefined, useMultimodal: boolean) {
  if (!data || useMultimodal) return false
  const normalized = question.trim().replace(/\s+/g, ' ')
  const wordCount = normalized ? normalized.split(/\s+/).length : 0
  const answerLength = data.answer.trim().length
  const asksForVisual = /(image|figure|diagram|table|formula|equation|visual|show|plot|graph|图片|图|表格|公式|可视化)/i.test(normalized)
  const asksForDeepTrace = /(why|how|explain|compare|analyze|trace|evidence|source|relationship|为什么|如何|解释|比较|分析|证据|来源|关系)/i.test(normalized)
  return wordCount <= 12 && answerLength <= 900 && !asksForVisual && !asksForDeepTrace
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
