import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Send, User, Bot, Code2, MessageSquare, Wrench,
  AlertTriangle, ChevronDown, Play, Copy, Check, Trash2, Loader2,
  Brain, Search, ChevronRight
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { motion, AnimatePresence } from 'framer-motion'
import { api, getToken } from '../utils/api'
import { useManufacturingKB } from '../hooks/useManufacturingKB'
import ManufacturingKBSelector from '../components/ManufacturingKBSelector'
import GCodeEditor from '../components/GCodeEditor'

const TABS = [
  { key: 'qa', icon: MessageSquare, label: '智能问答' },
  { key: 'code', icon: Code2, label: '代码解析' },
  { key: 'diagnosis', icon: Wrench, label: '故障诊断' },
]

const LANGUAGES = [
  { value: 'gcode', label: 'G 代码' },
  { value: 'plc_instruction_list', label: 'PLC 指令表' },
]

const markdownComponents = {
  h2: ({ children, ...props }) => <h2 className="text-base font-semibold text-warm-800 mt-4 mb-2 pb-1 border-b border-warm-200" {...props}>{children}</h2>,
  h3: ({ children, ...props }) => <h3 className="text-sm font-semibold text-warm-700 mt-3 mb-1" {...props}>{children}</h3>,
  p: ({ children, ...props }) => <p className="text-sm text-warm-600 leading-relaxed my-1.5" {...props}>{children}</p>,
  strong: ({ children, ...props }) => <strong className="font-semibold text-coral-600" {...props}>{children}</strong>,
  code: ({ inline, className, children, ...props }) => {
    const match = /language-(\w+)/.exec(className || '')
    return !inline ? (
      <div className="my-2 rounded-lg border border-warm-200 overflow-hidden">
        <div className="bg-warm-100 px-3 py-1 text-[10px] text-warm-500 font-mono">{match ? match[1] : 'code'}</div>
        <pre className="bg-warm-50 p-3 overflow-x-auto text-xs"><code className={className} {...props}>{children}</code></pre>
      </div>
    ) : (
      <code className="px-1.5 py-0.5 rounded-md text-xs font-mono bg-warm-100 text-amber-700" {...props}>{children}</code>
    )
  },
  table: ({ children }) => <div className="my-2 overflow-x-auto"><table className="min-w-full text-xs border-collapse">{children}</table></div>,
}

// Thinking step collapsible card
function ThinkingStep({ step, isLast }) {
  const [expanded, setExpanded] = useState(false)
  const isAction = step.action && step.action !== 'FINISH'
  const actionLabel = isAction
    ? (step.action === 'search' ? '检索知识库' : step.action === 'calculator' ? '计算' : step.action)
    : (step.action === 'FINISH' ? '完成推理' : '思考中')

  if (step._displayMode === 'status') {
    // Generic status message (no structured step data)
    return (
      <div className="flex items-center gap-1.5 text-2xs text-warm-500">
        <Loader2 size={10} className="animate-spin text-coral-400" />
        <span>{step.content || step.thought}</span>
      </div>
    )
  }

  return (
    <div className={`rounded-lg border text-xs overflow-hidden ${
      isAction ? 'border-sky-200 bg-sky-50/50' : 'border-warm-200 bg-warm-50/50'
    }`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-warm-100/50 transition-colors text-left"
      >
        <ChevronRight size={10} className={`text-warm-400 transition-transform ${expanded ? 'rotate-90' : ''}`} />
        {isAction ? (
          <Search size={11} className="text-sky-500 shrink-0" />
        ) : (
          <Brain size={11} className="text-coral-500 shrink-0" />
        )}
        <span className="font-medium text-warm-600">
          步骤 {step.step}: {actionLabel}
        </span>
        {step.elapsed_ms > 0 && (
          <span className="ml-auto text-2xs text-warm-500">{(step.elapsed_ms / 1000).toFixed(1)}s</span>
        )}
      </button>
      {expanded && (
        <div className="px-2.5 pb-2 space-y-1.5 border-t border-warm-100 pt-1.5">
          {step.thought && (
            <div>
              <p className="text-2xs text-warm-500 mb-0.5">思考</p>
              <p className="text-warm-600 leading-relaxed">{step.thought.length > 300 ? step.thought.slice(0, 300) + '...' : step.thought}</p>
            </div>
          )}
          {step.action && (
            <div>
              <p className="text-2xs text-warm-500 mb-0.5">行动</p>
              <code className="text-2xs px-1.5 py-0.5 rounded bg-white text-sky-600 font-mono">{step.action}</code>
            </div>
          )}
          {step.observation_preview && (
            <div>
              <p className="text-2xs text-warm-500 mb-0.5">观察</p>
              <p className="text-warm-500 italic leading-relaxed">{step.observation_preview}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function ManufacturingAgentPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [activeTab, setActiveTab] = useState('qa')
  const [loading, setLoading] = useState(false)

  // QA state
  const [qaMessages, setQaMessages] = useState([])
  const [qaInput, setQaInput] = useState('')
  const qaEndRef = useRef(null)
  const abortRef = useRef(null)

  // Abort streaming on unmount to prevent reader leaks
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
      }
    }
  }, [])

  // KB selector (shared hook)
  const { mfgKb, setMfgKb, kbList, kbLoading, creating, createMfgKb } = useManufacturingKB()

  // Code parser state
  const [codeInput, setCodeInput] = useState('')
  const [codeLang, setCodeLang] = useState('gcode')
  const [codeResult, setCodeResult] = useState(null)
  const [codeCopied, setCodeCopied] = useState(false)

  // Diagnosis state
  const [diagInput, setDiagInput] = useState('')
  const [diagSession, setDiagSession] = useState(null)
  const [diagMessages, setDiagMessages] = useState([])
  const diagEndRef = useRef(null)

  // Auto-scroll
  useEffect(() => { qaEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [qaMessages])
  useEffect(() => { diagEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [diagMessages])

  // === QA (streaming with AgenticRAG trace) ===
  const cancelQA = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setLoading(false)
    }
  }

  const handleQASend = async (presetQuery) => {
    const query = (presetQuery || qaInput).trim()
    if (!query || loading) return
    setQaInput('')
    const msgId = Date.now()
    setQaMessages(prev => [...prev, { role: 'user', content: query }])
    setQaMessages(prev => [...prev, { role: 'assistant', content: '', _streaming: true, _id: msgId, _thinking: [] }])
    setLoading(true)

    // Cancel any in-flight request
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = getToken()
      const res = await fetch(`/api/manufacturing/qa/stream?kb=${mfgKb}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ query }),
        signal: controller.signal,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const evt = JSON.parse(line.slice(6))
            if (evt.type === 'thinking' && evt.step) {
              // AgenticRAG reasoning step
              setQaMessages(prev => prev.map(m =>
                m._id === msgId ? { ...m, _thinking: [...m._thinking, evt] } : m
              ))
            } else if (evt.type === 'thinking' && !evt.step) {
              // Generic status message (explicit display mode, not sentinel step:0)
              setQaMessages(prev => prev.map(m =>
                m._id === msgId ? { ...m, _thinking: [...m._thinking, { ...evt, _displayMode: 'status' }] } : m
              ))
            } else if (evt.type === 'token') {
              setQaMessages(prev => prev.map(m =>
                m._id === msgId ? { ...m, content: m.content + evt.content } : m
              ))
            } else if (evt.type === 'images') {
              setQaMessages(prev => prev.map(m =>
                m._id === msgId ? { ...m, _images: evt.images } : m
              ))
            } else if (evt.type === 'done') {
              setQaMessages(prev => prev.map(m =>
                m._id === msgId ? {
                  ...m, _streaming: false, _id: undefined,
                  time: evt.elapsed * 1000,
                  confidence: evt.confidence,
                } : m
              ))
            } else if (evt.type === 'error') {
              setQaMessages(prev => prev.map(m =>
                m._id === msgId ? { ...m, content: m.content || evt.content, _streaming: false, _id: undefined } : m
              ))
            }
          } catch (parseErr) {
            console.warn('[ManufacturingQA] SSE parse error:', parseErr.message, 'line:', line.slice(0, 100))
          }
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        setQaMessages(prev => prev.map(m =>
          m._id === msgId ? { ...m, content: m.content || '（已取消）', _streaming: false, _id: undefined } : m
        ))
      } else {
        setQaMessages(prev => prev.map(m =>
          m._id === msgId ? { ...m, content: m.content || `请求失败: ${e.message}`, _streaming: false, _id: undefined } : m
        ))
      }
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }

  // === Code Parser ===
  const handleCodeParse = async () => {
    if (!codeInput.trim() || loading) return
    setLoading(true)
    setCodeResult(null)
    try {
      const res = await api.post(`/manufacturing/code/parse?kb=${mfgKb}`, { query: codeInput, language: codeLang })
      setCodeResult(res?.data || res)
    } catch (e) {
      setCodeResult({ error: '解析请求失败' })
    } finally { setLoading(false) }
  }

  // === Fault Diagnosis ===
  const startDiagnosis = async (presetDesc) => {
    const desc = (presetDesc || diagInput).trim()
    if (!desc || loading) return
    setDiagInput('')
    setDiagMessages([{ role: 'user', content: desc }])
    setLoading(true)
    try {
      const res = await api.post(`/manufacturing/fault-diagnosis?kb=${mfgKb}`, { query: desc })
      const data = res?.data || res
      setDiagSession(data.session_id)
      setDiagMessages(prev => [...prev, {
        role: 'assistant',
        content: data.next_question,
        initial_matches: data.initial_matches,
        cases: data.matched_cases,
      }])
    } catch (e) {
      setDiagMessages(prev => [...prev, { role: 'assistant', content: '诊断服务请求失败' }])
    } finally { setLoading(false) }
  }

  const continueDiagnosis = async (answer) => {
    if (!diagSession || loading) return
    setDiagMessages(prev => [...prev, { role: 'user', content: answer }])
    setLoading(true)
    try {
      const res = await api.post(`/manufacturing/fault-diagnosis/continue?kb=${mfgKb}`, {
        session_id: diagSession,
        query: answer,
      })
      const data = res?.data || res
      if (data.diagnosis) {
        // Final result
        const d = data.diagnosis
        const summary = [
          `### 诊断结论 (置信度: ${(d.confidence * 100).toFixed(0)}%)`,
          '',
          '**可能原因：**',
          ...d.possible_causes.map((c, i) => `- ${c.description} (匹配度 ${(c.confidence * 100).toFixed(0)}%)`),
          '',
          '**建议操作：**',
          ...(d.recommended_actions || []).map(a => `- ${a}`),
          d.needs_human_review ? '\n⚠️ 置信度较低，建议人工确认' : '',
        ].join('\n')
        setDiagMessages(prev => [...prev, { role: 'assistant', content: summary, isFinal: true }])
        setDiagSession(null)
      } else {
        setDiagMessages(prev => [...prev, {
          role: 'assistant',
          content: data.next_question,
          confidence: data.current_confidence,
        }])
      }
    } catch (e) {
      setDiagMessages(prev => [...prev, { role: 'assistant', content: '诊断请求失败' }])
    } finally { setLoading(false) }
  }

  // Quick-reply for diagnosis
  const quickReply = (text) => continueDiagnosis(text)

  return (
    <div className="space-y-4 h-[calc(100vh-140px)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-semibold text-warm-800 flex items-center gap-2">
            <Bot size={22} className="text-coral-500" />
            制造智能体
          </h1>
          <p className="text-sm text-warm-500 mt-1">智能问答 · 代码解析 · 故障诊断</p>
          <div className="flex gap-1 mt-2">
            {[
              { to: '/manufacturing', label: '仪表板' },
              { to: '/manufacturing/knowledge', label: '知识库' },
              { to: '/manufacturing/agent', label: '智能体' },
            ].map(item => (
              <button key={item.to} onClick={() => navigate(item.to)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                  location.pathname === item.to
                    ? 'bg-coral-50 text-coral-600'
                    : 'text-warm-500 hover:text-warm-700 hover:bg-warm-100'
                }`}>
                {item.label}
              </button>
            ))}
          </div>
        </div>
        <ManufacturingKBSelector
          mfgKb={mfgKb} kbList={kbList} loading={kbLoading} creating={creating}
          onChange={setMfgKb} onCreate={createMfgKb}
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-warm-100 rounded-xl w-fit shrink-0">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === t.key ? 'bg-white text-warm-800 shadow-sm' : 'text-warm-500 hover:text-warm-700'
            }`}>
            <t.icon size={15} /> {t.label}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        {/* ========== QA TAB ========== */}
        {activeTab === 'qa' && (
          <motion.div key="qa" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex-1 flex flex-col min-h-0">
            {/* Messages */}
            <div className="flex-1 overflow-y-auto space-y-4 pr-2 mb-4">
              {qaMessages.length === 0 && (
                <div className="text-center py-16 text-warm-400">
                  <MessageSquare size={40} className="mx-auto mb-3 opacity-30" />
                  <p className="text-sm">输入你的制造领域问题，智能体将基于知识库回答</p>
                  <div className="flex flex-wrap justify-center gap-2 mt-4">
                    {['数控铣削的切削参数如何选择？', 'PLC 程序梯形图设计原则', '如何检测加工中心的定位精度？'].map(q => (
                      <button key={q} onClick={() => handleQASend(q)}
                        className="px-3 py-1.5 rounded-full text-xs bg-warm-100 text-warm-600 hover:bg-coral-50 hover:text-coral-600 transition-colors">
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {qaMessages.map((msg, i) => (
                <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}>
                  {msg.role === 'assistant' && (
                    <div className="w-7 h-7 rounded-full bg-coral-100 flex items-center justify-center shrink-0 mt-0.5">
                      <Bot size={14} className="text-coral-500" />
                    </div>
                  )}
                  <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                    msg.role === 'user'
                      ? 'bg-coral-700 text-white'
                      : 'bg-warm-50 border border-warm-100'
                  }`}>
                    {msg.role === 'user' ? (
                      <p className="text-sm">{msg.content}</p>
                    ) : (
                      <div className="text-sm text-warm-700">
                        {/* Thinking steps (AgenticRAG trace) */}
                        {msg._thinking && msg._thinking.length > 0 && (
                          <div className="mb-3 space-y-1.5">
                            {msg._thinking.map((step, si) => (
                              <ThinkingStep key={si} step={step} isLast={si === msg._thinking.length - 1 && !msg._streaming} />
                            ))}
                          </div>
                        )}
                        <ReactMarkdown components={markdownComponents}>{msg.content || (msg._streaming ? '▊' : '')}</ReactMarkdown>
                        {msg._streaming && (
                          <span className="inline-block w-1.5 h-4 bg-coral-400 animate-pulse rounded-sm ml-0.5 align-middle" />
                        )}
                        {/* Matched images */}
                        {msg._images && msg._images.length > 0 && (
                          <div className="mt-3 space-y-2">
                            {msg._images.map((img, ii) => (
                              <div key={ii} className="rounded-lg overflow-hidden border border-warm-200">
                                <img src={img.data_url} alt={img.caption} className="w-full max-h-48 object-contain bg-warm-50" />
                                <p className="text-2xs text-warm-500 px-2 py-1">{img.caption} (页 {img.page})</p>
                              </div>
                            ))}
                          </div>
                        )}
                        {msg.time && (
                          <div className="mt-2 text-2xs text-warm-400 flex items-center gap-3">
                            <span>{msg.time.toFixed(0)}ms</span>
                            {msg.confidence !== undefined && (
                              <span className="text-coral-500">置信度 {(msg.confidence * 100).toFixed(0)}%</span>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  {msg.role === 'user' && (
                    <div className="w-7 h-7 rounded-full bg-warm-200 flex items-center justify-center shrink-0 mt-0.5">
                      <User size={14} className="text-warm-500" />
                    </div>
                  )}
                </div>
              ))}
              {loading && activeTab === 'qa' && (
                <div className="flex gap-3">
                  <div className="w-7 h-7 rounded-full bg-coral-100 flex items-center justify-center">
                    <Loader2 size={14} className="text-coral-500 animate-spin" />
                  </div>
                  <div className="bg-warm-50 border border-warm-100 rounded-2xl px-4 py-3">
                    <div className="flex gap-1.5">
                      <div className="w-2 h-2 rounded-full bg-coral-400 animate-pulse" />
                      <div className="w-2 h-2 rounded-full bg-coral-400 animate-pulse" style={{ animationDelay: '0.15s' }} />
                      <div className="w-2 h-2 rounded-full bg-coral-400 animate-pulse" style={{ animationDelay: '0.3s' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={qaEndRef} />
            </div>

            {/* Input */}
            <div className="shrink-0 flex gap-2">
              <input value={qaInput} onChange={e => setQaInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleQASend()}
                placeholder="输入制造领域问题…"
                className="flex-1 px-4 py-3 rounded-xl border border-warm-200 text-sm bg-white
                  focus:outline-none focus:border-coral-300 focus:ring-2 focus:ring-coral-50 transition-all" />
              {loading && activeTab === 'qa' ? (
                <button onClick={cancelQA}
                  className="btn-danger px-5 py-3 rounded-xl">
                  取消
                </button>
              ) : (
                <button onClick={handleQASend} disabled={!qaInput.trim()}
                  className="btn-primary px-5 py-3 rounded-xl disabled:opacity-50">
                  <Send size={16} />
                </button>
              )}
            </div>
          </motion.div>
        )}

        {/* ========== CODE PARSER TAB ========== */}
        {activeTab === 'code' && (
          <motion.div key="code" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex-1 min-h-0 overflow-y-auto">
            {!codeResult && (
              <div className="text-center py-8 text-warm-400">
                <Code2 size={32} className="mx-auto mb-2 opacity-30" />
                <p className="text-sm">粘贴 G 代码或 PLC 程序进行分析</p>
                <p className="text-xs text-warm-400 mt-1">支持 G 代码语法高亮、指令解释与风险检测</p>
              </div>
            )}
            <GCodeEditor onParseResult={(data) => setCodeResult(data)} />
            {/* IO Signals (PLC) */}
            {codeResult?.io_signals && (
              <div className="grid grid-cols-2 gap-3 mt-4">
                <div className="p-2 rounded-lg bg-sky-50 border border-sky-100 text-xs">
                  <p className="font-medium text-sky-600 mb-1">输入信号 ({codeResult.io_signals.inputs.length})</p>
                  <div className="flex flex-wrap gap-1">
                    {codeResult.io_signals.inputs.map((s, j) => (
                      <code key={j} className="px-1.5 py-0.5 rounded bg-white text-sky-700 font-mono">{s}</code>
                    ))}
                  </div>
                </div>
                <div className="p-2 rounded-lg bg-amber-50 border border-amber-100 text-xs">
                  <p className="font-medium text-amber-600 mb-1">输出信号 ({codeResult.io_signals.outputs.length})</p>
                  <div className="flex flex-wrap gap-1">
                    {codeResult.io_signals.outputs.map((s, j) => (
                      <code key={j} className="px-1.5 py-0.5 rounded bg-white text-amber-700 font-mono">{s}</code>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </motion.div>
        )}

        {/* ========== FAULT DIAGNOSIS TAB ========== */}
        {activeTab === 'diagnosis' && (
          <motion.div key="diagnosis" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex-1 flex flex-col min-h-0">
            {/* Messages */}
            <div className="flex-1 overflow-y-auto space-y-4 pr-2 mb-4">
              {diagMessages.length === 0 && (
                <div className="text-center py-16 text-warm-400">
                  <Wrench size={40} className="mx-auto mb-3 opacity-30" />
                  <p className="text-sm">描述设备故障现象，智能体将进行交互式诊断</p>
                  <div className="flex flex-wrap justify-center gap-2 mt-4">
                    {['加工精度超差，误差约0.05mm', '主轴运转时有异常振动', 'PLC 输出信号无响应'].map(q => (
                      <button key={q} onClick={() => startDiagnosis(q)}
                        className="px-3 py-1.5 rounded-full text-xs bg-warm-100 text-warm-600 hover:bg-coral-50 hover:text-coral-600 transition-colors">
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {diagMessages.map((msg, i) => (
                <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}>
                  {msg.role === 'assistant' && (
                    <div className="w-7 h-7 rounded-full bg-amber-100 flex items-center justify-center shrink-0 mt-0.5">
                      <Wrench size={14} className="text-amber-600" />
                    </div>
                  )}
                  <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                    msg.role === 'user'
                      ? 'bg-amber-800 text-white'
                      : 'bg-warm-50 border border-warm-100'
                  }`}>
                    {msg.role === 'user' ? (
                      <p className="text-sm">{msg.content}</p>
                    ) : (
                      <div className="text-sm text-warm-700">
                        {msg.isFinal ? (
                          <ReactMarkdown components={markdownComponents}>{msg.content}</ReactMarkdown>
                        ) : (
                          <>
                            <p>{msg.content}</p>
                            {msg.initial_matches !== undefined && (
                              <p className="text-xs text-warm-500 mt-1">匹配到 {msg.initial_matches} 个相似案例</p>
                            )}
                            {msg.confidence !== undefined && (
                              <p className="text-xs text-warm-500 mt-1">当前置信度 {(msg.confidence * 100).toFixed(0)}%</p>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  {msg.role === 'user' && (
                    <div className="w-7 h-7 rounded-full bg-warm-200 flex items-center justify-center shrink-0 mt-0.5">
                      <User size={14} className="text-warm-500" />
                    </div>
                  )}
                </div>
              ))}
              {/* Quick reply buttons for active diagnosis */}
              {diagSession && !loading && (
                <div className="flex flex-wrap gap-2 pl-10">
                  {(() => {
                    // Use backend-suggested replies when available, fall back to defaults
                    const lastMsg = diagMessages[diagMessages.length - 1]
                    const replies = lastMsg?.suggested_replies?.length
                      ? lastMsg.suggested_replies
                      : ['是', '否', '不确定', '故障刚发生', '故障持续存在', '之前发生过']
                    return replies.map(opt => (
                      <button key={opt} onClick={() => quickReply(opt)}
                        className="px-3 py-1 rounded-full text-xs bg-amber-50 text-amber-700 hover:bg-amber-100 hover:text-amber-800 border border-amber-200 transition-colors">
                        {opt}
                      </button>
                    ))
                  })()}
                </div>
              )}
              {loading && activeTab === 'diagnosis' && (
                <div className="flex gap-3">
                  <div className="w-7 h-7 rounded-full bg-amber-100 flex items-center justify-center">
                    <Loader2 size={14} className="text-amber-500 animate-spin" />
                  </div>
                  <div className="bg-warm-50 border border-warm-100 rounded-2xl px-4 py-3">
                    <div className="flex gap-1.5">
                      <div className="w-2 h-2 rounded-full bg-coral-400 animate-pulse" />
                      <div className="w-2 h-2 rounded-full bg-coral-400 animate-pulse" style={{ animationDelay: '0.15s' }} />
                      <div className="w-2 h-2 rounded-full bg-coral-400 animate-pulse" style={{ animationDelay: '0.3s' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={diagEndRef} />
            </div>

            {/* Input — always visible so users can type custom responses */}
            <div className="shrink-0 flex gap-2">
              <textarea value={diagInput} onChange={e => setDiagInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    diagSession ? continueDiagnosis(diagInput) : startDiagnosis()
                  }
                }}
                placeholder={diagSession ? '回答诊断问题或输入补充信息…' : '描述设备故障现象…'}
                rows={2}
                className="flex-1 px-4 py-3 rounded-xl border border-warm-200 text-sm bg-white resize-none
                  focus:outline-none focus:border-amber-300 focus:ring-2 focus:ring-amber-50 transition-all" />
              <button onClick={() => diagSession ? continueDiagnosis(diagInput) : startDiagnosis()}
                disabled={loading || !diagInput.trim()}
                className="btn-primary px-5 py-3 rounded-xl disabled:opacity-50 bg-amber-500 hover:bg-amber-600">
                <Send size={16} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
