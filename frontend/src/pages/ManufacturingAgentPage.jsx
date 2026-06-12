import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Send, User, Bot, Code2, MessageSquare, Wrench,
  AlertTriangle, ChevronDown, Play, Copy, Check, Trash2, Loader2
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '../utils/api'
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

export default function ManufacturingAgentPage() {
  const [activeTab, setActiveTab] = useState('qa')
  const [loading, setLoading] = useState(false)

  // QA state
  const [qaMessages, setQaMessages] = useState([])
  const [qaInput, setQaInput] = useState('')
  const qaEndRef = useRef(null)

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

  // === QA ===
  const handleQASend = async () => {
    if (!qaInput.trim() || loading) return
    const query = qaInput.trim()
    setQaInput('')
    setQaMessages(prev => [...prev, { role: 'user', content: query }])
    setLoading(true)
    try {
      const res = await api.post('/manufacturing/qa', { query })
      const data = res?.data || res
      setQaMessages(prev => [...prev, {
        role: 'assistant',
        content: data.answer || '未获取到回答',
        citations: data.citations,
        confidence: data.confidence,
        time: data.processing_time_ms,
      }])
    } catch (e) {
      setQaMessages(prev => [...prev, { role: 'assistant', content: '问答请求失败，请检查后端服务。' }])
    } finally { setLoading(false) }
  }

  // === Code Parser ===
  const handleCodeParse = async () => {
    if (!codeInput.trim() || loading) return
    setLoading(true)
    setCodeResult(null)
    try {
      const res = await api.post('/manufacturing/code/parse', { query: codeInput, language: codeLang })
      setCodeResult(res?.data || res)
    } catch (e) {
      setCodeResult({ error: '解析请求失败' })
    } finally { setLoading(false) }
  }

  // === Fault Diagnosis ===
  const startDiagnosis = async () => {
    if (!diagInput.trim() || loading) return
    const desc = diagInput.trim()
    setDiagInput('')
    setDiagMessages([{ role: 'user', content: desc }])
    setLoading(true)
    try {
      const res = await api.post('/manufacturing/fault-diagnosis', { query: desc })
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
      const res = await api.post('/manufacturing/fault-diagnosis/continue', {
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
        </div>
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
                      <button key={q} onClick={() => { setQaInput(q); /* trigger send after state update */ setTimeout(() => handleQASend(), 50) }}
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
                      ? 'bg-coral-500 text-white'
                      : 'bg-warm-50 border border-warm-100'
                  }`}>
                    {msg.role === 'user' ? (
                      <p className="text-sm">{msg.content}</p>
                    ) : (
                      <div className="text-sm text-warm-700">
                        <ReactMarkdown components={markdownComponents}>{msg.content}</ReactMarkdown>
                        {msg.citations?.length > 0 && (
                          <div className="mt-2 pt-2 border-t border-warm-200">
                            <p className="text-2xs text-warm-500 mb-1">来源引用：</p>
                            {msg.citations.slice(0, 3).map((c, j) => (
                              <div key={j} className="text-2xs text-warm-500 flex items-center gap-1">
                                <span className="font-medium text-coral-500">[{j + 1}]</span>
                                {c.source_title}{c.page ? ` p.${c.page}` : ''}
                              </div>
                            ))}
                          </div>
                        )}
                        {msg.confidence !== undefined && (
                          <div className="mt-2 flex items-center gap-3 text-2xs text-warm-400">
                            <span>置信度 {(msg.confidence * 100).toFixed(0)}%</span>
                            {msg.time && <span>{msg.time.toFixed(0)}ms</span>}
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
                      <div className="w-2 h-2 rounded-full bg-warm-300 animate-bounce" />
                      <div className="w-2 h-2 rounded-full bg-warm-300 animate-bounce" style={{ animationDelay: '0.1s' }} />
                      <div className="w-2 h-2 rounded-full bg-warm-300 animate-bounce" style={{ animationDelay: '0.2s' }} />
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
              <button onClick={handleQASend} disabled={loading || !qaInput.trim()}
                className="btn-primary px-5 py-3 rounded-xl disabled:opacity-50">
                <Send size={16} />
              </button>
            </div>
          </motion.div>
        )}

        {/* ========== CODE PARSER TAB ========== */}
        {activeTab === 'code' && (
          <motion.div key="code" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex-1 min-h-0 overflow-y-auto">
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
                      <button key={q} onClick={() => { setDiagInput(q); setTimeout(() => startDiagnosis(), 50) }}
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
                      ? 'bg-amber-500 text-white'
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
                  {['是', '否', '不确定', '故障刚发生', '故障持续存在', '之前发生过'].map(opt => (
                    <button key={opt} onClick={() => quickReply(opt)}
                      className="px-3 py-1 rounded-full text-xs bg-warm-100 text-warm-600 hover:bg-amber-50 hover:text-amber-600 transition-colors">
                      {opt}
                    </button>
                  ))}
                </div>
              )}
              {loading && activeTab === 'diagnosis' && (
                <div className="flex gap-3">
                  <div className="w-7 h-7 rounded-full bg-amber-100 flex items-center justify-center">
                    <Loader2 size={14} className="text-amber-500 animate-spin" />
                  </div>
                  <div className="bg-warm-50 border border-warm-100 rounded-2xl px-4 py-3">
                    <div className="flex gap-1.5">
                      <div className="w-2 h-2 rounded-full bg-warm-300 animate-bounce" />
                      <div className="w-2 h-2 rounded-full bg-warm-300 animate-bounce" style={{ animationDelay: '0.1s' }} />
                      <div className="w-2 h-2 rounded-full bg-warm-300 animate-bounce" style={{ animationDelay: '0.2s' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={diagEndRef} />
            </div>

            {/* Input */}
            {!diagSession && (
              <div className="shrink-0 flex gap-2">
                <input value={diagInput} onChange={e => setDiagInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && startDiagnosis()}
                  placeholder="描述设备故障现象…"
                  className="flex-1 px-4 py-3 rounded-xl border border-warm-200 text-sm bg-white
                    focus:outline-none focus:border-amber-300 focus:ring-2 focus:ring-amber-50 transition-all" />
                <button onClick={startDiagnosis} disabled={loading || !diagInput.trim()}
                  className="btn-primary px-5 py-3 rounded-xl disabled:opacity-50 bg-amber-500 hover:bg-amber-600">
                  <Play size={16} />
                </button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
