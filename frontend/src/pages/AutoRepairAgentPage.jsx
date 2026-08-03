import { useState, useEffect, useRef, useCallback, Component } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Send, User, Bot, Code2, MessageSquare, Wrench,
  AlertTriangle, ChevronDown, Play, Copy, Check, Trash2, Loader2,
  Brain, Search, ChevronRight
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { motion, AnimatePresence } from 'framer-motion'
import { api, streamSSE } from '../utils/api'
import { useAutoRepairKB } from '../hooks/useAutoRepairKB'
import { useAuth } from '../context/AuthContext'
import AutoRepairKBSelector from '../components/AutoRepairKBSelector'
import { ControlledMediaImage } from '../components/ControlledMedia'
import GCodeEditor from '../components/GCodeEditor'

const TABS = [
  { key: 'qa', icon: MessageSquare, label: '维修问答' },
  { key: 'code', icon: Code2, label: '故障码解析' },
  { key: 'diagnosis', icon: Wrench, label: '故障诊断' },
]

const LANGUAGES = [
  { value: 'gcode', label: 'OBD 故障码 (DTC)' },
  { value: 'plc_instruction_list', label: 'ECU 数据流' },
]

const markdownComponents = {
  h2: ({ children, ...props }) => <h2 className="text-base font-semibold text-ink-primary mt-4 mb-2 pb-1 border-b border-cloud-300" {...props}>{children}</h2>,
  h3: ({ children, ...props }) => <h3 className="text-sm font-semibold text-ink-body mt-3 mb-1" {...props}>{children}</h3>,
  p: ({ children, ...props }) => <p className="text-sm text-ink-body leading-relaxed my-1.5" {...props}>{children}</p>,
  strong: ({ children, ...props }) => <strong className="font-semibold text-sky-600" {...props}>{children}</strong>,
  code: ({ inline, className, children, ...props }) => {
    const match = /language-(\w+)/.exec(className || '')
    return !inline ? (
      <div className="my-2 rounded-lg border border-cloud-300 overflow-hidden">
        <div className="bg-cloud-100 px-3 py-1 text-2xs text-ink-muted font-mono">{match ? match[1] : 'code'}</div>
        <pre className="bg-cloud-200 p-3 overflow-x-auto text-xs"><code className={className} {...props}>{children}</code></pre>
      </div>
    ) : (
      <code className="px-1.5 py-0.5 rounded-md text-xs font-mono bg-cloud-100 text-amber-700" {...props}>{children}</code>
    )
  },
  table: ({ children }) => <div className="my-2 overflow-x-auto"><table className="min-w-full text-xs border-collapse">{children}</table></div>,
}

// 轻量错误边界，避免单点崩溃导致整页空白
class ManufacturingAgentErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null } }
  static getDerivedStateFromError(error) { return { hasError: true, error } }
  componentDidCatch(error, info) { console.error('[ManufacturingAgent] Render error:', error, info) }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center py-24">
          <div className="text-center space-y-3 max-w-sm">
            <AlertTriangle size={32} className="mx-auto text-rose-400" />
            <p className="text-sm font-medium text-ink-body">汽修智能助手页面加载异常</p>
            <p className="text-xs text-ink-muted">{this.state.error?.message || '未知错误'}</p>
            <button onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload() }}
              className="px-4 py-2 text-xs font-medium text-white bg-sky-500 rounded-lg hover:bg-sky-600 transition-colors">
              刷新页面
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

// 可折叠的思考步骤卡片
function ThinkingStep({ step, isLast }) {
  const [expanded, setExpanded] = useState(false)
  const isAction = step.action && step.action !== 'FINISH'
  const actionLabel = isAction
    ? (step.action === 'search' ? '检索知识库' : step.action === 'calculator' ? '计算' : step.action)
    : (step.action === 'FINISH' ? '完成推理' : '思考中')

  if (step._displayMode === 'status') {
    // 通用状态消息（无结构化步骤数据）
    return (
      <div className="flex items-center gap-1.5 text-2xs text-ink-muted">
        <Loader2 size={10} className="animate-spin text-sky-400" />
        <span>{step.content || step.thought}</span>
      </div>
    )
  }

  return (
    <div className={`rounded-lg border text-xs overflow-hidden ${
      isAction ? 'border-sky-200 bg-sky-50/50' : 'border-cloud-300 bg-cloud-200/50'
    }`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-cloud-100/50 transition-colors text-left"
      >
        <ChevronRight size={10} className={`text-ink-muted transition-transform ${expanded ? 'rotate-90' : ''}`} />
        {isAction ? (
          <Search size={11} className="text-sky-500 shrink-0" />
        ) : (
          <Brain size={11} className="text-sky-500 shrink-0" />
        )}
        <span className="font-medium text-ink-body">
          步骤 {step.step}: {actionLabel}
        </span>
        {step.elapsed_ms > 0 && (
          <span className="ml-auto text-2xs text-ink-muted">{(step.elapsed_ms / 1000).toFixed(1)}s</span>
        )}
      </button>
      {expanded && (
        <div className="px-2.5 pb-2 space-y-1.5 border-t border-cloud-200 pt-1.5">
          {step.thought && (
            <div>
              <p className="text-2xs text-ink-muted mb-0.5">思考</p>
              <p className="text-ink-body leading-relaxed">{step.thought.length > 300 ? step.thought.slice(0, 300) + '...' : step.thought}</p>
            </div>
          )}
          {step.action && (
            <div>
              <p className="text-2xs text-ink-muted mb-0.5">行动</p>
              <code className="text-2xs px-1.5 py-0.5 rounded bg-white text-sky-600 font-mono">{step.action}</code>
            </div>
          )}
          {step.observation_preview && (
            <div>
              <p className="text-2xs text-ink-muted mb-0.5">观察</p>
              <p className="text-ink-muted italic leading-relaxed">{step.observation_preview}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function AutoRepairAgentPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { isAdmin, hasPermission } = useAuth()
  const canInteract = isAdmin || hasPermission('autorepair:write')
  const [activeTab, setActiveTab] = useState('qa')
  const [loading, setLoading] = useState(false)

  // 问答状态
  const [qaMessages, setQaMessages] = useState([])
  const [qaInput, setQaInput] = useState('')
  const qaEndRef = useRef(null)
  const abortRef = useRef(null)

  // 卸载时中止流式请求，避免读取器泄漏
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
      }
    }
  }, [])

  // 知识库选择器（共享 hook）
  const { arKb, setArKb, kbList, kbLoading, creating, canCreateArKb, createArKb } = useAutoRepairKB()

  // 代码解析状态
  const [codeResult, setCodeResult] = useState(null)

  // 诊断状态
  const [diagInput, setDiagInput] = useState('')
  const [diagSession, setDiagSession] = useState(null)
  const [diagMessages, setDiagMessages] = useState([])
  const diagEndRef = useRef(null)

  // 自动滚动
  const scrollToMarker = useCallback((ref) => {
    const marker = ref.current
    if (!marker?.parentElement) return
    window.requestAnimationFrame(() => {
      marker.parentElement.scrollTo({ top: marker.parentElement.scrollHeight, behavior: 'smooth' })
    })
  }, [])
  useEffect(() => { scrollToMarker(qaEndRef) }, [qaMessages, scrollToMarker])
  useEffect(() => { scrollToMarker(diagEndRef) }, [diagMessages, scrollToMarker])

  // === 问答（带 AgenticRAG 流式轨迹）===
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

    // 取消任何进行中的请求
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    try {
      await streamSSE(`/api/autorepair/qa/stream?kb=${arKb}`, {
        method: 'POST',
        body: JSON.stringify({ query }),
        signal: controller.signal,
        onEvent: evt => {
          if (evt.type === 'thinking' && evt.step) {
              // AgenticRAG 推理步骤
              setQaMessages(prev => prev.map(m =>
                m._id === msgId ? { ...m, _thinking: [...m._thinking, evt] } : m
              ))
          } else if (evt.type === 'thinking' && !evt.step) {
              // 通用状态消息（显式展示模式，不使用 step:0 哨兵值）
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
        },
        onParseError: (parseErr, payload) => {
          console.warn('[ManufacturingQA] SSE parse error:', parseErr.message, 'line:', payload.slice(0, 100))
        },
      })
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

  // === 故障诊断 ===
  const startDiagnosis = async (presetDesc) => {
    const desc = (presetDesc || diagInput).trim()
    if (!desc || loading) return
    setDiagInput('')
    setDiagMessages([{ role: 'user', content: desc }])
    setLoading(true)
    try {
      const res = await api.post(`/autorepair/fault-diagnosis?kb=${arKb}`, { query: desc })
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
      const res = await api.post(`/autorepair/fault-diagnosis/continue?kb=${arKb}`, {
        session_id: diagSession,
        query: answer,
      })
      const data = res?.data || res
      if (data.diagnosis) {
        // 最终结果
        const d = data.diagnosis
        const summary = [
          `### 诊断结论 (置信度: ${(d.confidence * 100).toFixed(0)}%)`,
          '',
          '**可能原因：**',
          ...d.possible_causes.map((c, i) => `- ${c.description} (匹配度 ${(c.confidence * 100).toFixed(0)}%)`),
          '',
          '**建议操作：**',
          ...(d.recommended_actions || []).map(a => `- ${a}`),
          d.needs_human_review ? '\n注意：置信度较低，建议人工确认' : '',
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

  // 诊断快捷回复
  const quickReply = (text) => continueDiagnosis(text)

  return (
    <ManufacturingAgentErrorBoundary>
    <div className="space-y-4 h-[calc(100vh-140px)] flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-semibold text-ink-primary flex items-center gap-2">
            <Bot size={22} className="text-sky-500" />
            汽修智能助手
          </h1>
          <p className="text-sm text-ink-muted mt-1">维修问答 · 故障码解析 · 故障诊断</p>
          <div className="flex gap-1 mt-2">
            {[
              { to: '/autorepair', label: '诊断看板' },
              { to: '/autorepair/knowledge', label: '知识库' },
              { to: '/autorepair/agent', label: '智能体' },
            ].map(item => (
              <button key={item.to} onClick={() => navigate(item.to)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                  location.pathname === item.to
                    ? 'bg-sky-50 text-sky-600'
                    : 'text-ink-muted hover:text-ink-body hover:bg-cloud-100'
                }`}>
                {item.label}
              </button>
            ))}
          </div>
        </div>
        <AutoRepairKBSelector
          arKb={arKb} kbList={kbList} loading={kbLoading} creating={creating}
          onChange={setArKb} onCreate={createArKb} canCreate={canCreateArKb}
        />
      </div>

      {!canInteract && (
        <div className="rounded-xl border border-cloud-200 bg-cloud-100 px-3 py-2 text-xs text-ink-muted" role="status">
          当前为只读模式：无 autorepair:write 权限，问答与故障诊断输入已禁用。
        </div>
      )}

      {/* 标签页 */}
      <div className="flex gap-1 p-1 bg-cloud-100 rounded-xl w-fit shrink-0">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === t.key ? 'bg-white text-ink-primary shadow-sm' : 'text-ink-muted hover:text-ink-body'
            }`}>
            <t.icon size={15} /> {t.label}
          </button>
        ))}
      </div>

      <AnimatePresence mode="sync">
        {/* ========== 问答标签页 ========== */}
        {activeTab === 'qa' && (
          <motion.div key="qa" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex-1 flex flex-col min-h-0">
            {/* 消息列表 */}
            <div className="flex-1 overflow-y-auto space-y-4 pr-2 mb-4">
              {qaMessages.length === 0 && (
                <div className="text-center py-16 text-ink-muted">
                  <MessageSquare size={40} className="mx-auto mb-3 opacity-30" />
                  <p className="text-sm">输入汽车维修问题，智能助手将基于知识库回答</p>
                  {canInteract && (
                    <div className="flex flex-wrap justify-center gap-2 mt-4">
                      {['发动机怠速抖动如何诊断？', '自动变速箱故障码 P0730 解析', '如何检测氧传感器信号异常？'].map(q => (
                        <button key={q} onClick={() => handleQASend(q)}
                          className="px-3 py-1.5 rounded-full text-xs bg-cloud-100 text-ink-body hover:bg-sky-50 hover:text-sky-600 transition-colors">
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {qaMessages.map((msg, i) => (
                <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}>
                  {msg.role === 'assistant' && (
                    <div className="w-7 h-7 rounded-full bg-sky-100 dark:bg-sky-900/40 flex items-center justify-center shrink-0 mt-0.5">
                      <Bot size={14} className="text-sky-500" />
                    </div>
                  )}
                  <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                    msg.role === 'user'
                      ? 'bg-sky-500 dark:bg-sky-600 text-white'
                      : 'bg-cloud-200 border border-cloud-200'
                  }`}>
                    {msg.role === 'user' ? (
                      <p className="text-sm">{msg.content}</p>
                    ) : (
                      <div className="text-sm text-ink-body">
                        {/* 思考步骤（AgenticRAG 轨迹） */}
                        {msg._thinking && msg._thinking.length > 0 && (
                          <div className="mb-3 space-y-1.5">
                            {msg._thinking.map((step, si) => (
                              <ThinkingStep key={si} step={step} isLast={si === msg._thinking.length - 1 && !msg._streaming} />
                            ))}
                          </div>
                        )}
                        <ReactMarkdown components={markdownComponents}>{msg.content || (msg._streaming ? '▊' : '')}</ReactMarkdown>
                        {msg._streaming && (
                          <span className="inline-block w-1.5 h-4 bg-sky-400 animate-pulse rounded-sm ml-0.5 align-middle" />
                        )}
                        {/* 匹配图片 */}
                        {msg._images && msg._images.length > 0 && (
                          <div className="mt-3 space-y-2">
                            {msg._images.map((img, ii) => (
                              <div key={ii} className="rounded-lg overflow-hidden border border-cloud-300">
                                <ControlledMediaImage media={img} alt={img.caption || 'Related image'} className="w-full max-h-48 object-contain bg-cloud-200" />
                                <p className="text-2xs text-ink-muted px-2 py-1">{(img.caption && String(img.caption).trim()) || 'Related image'}{Number.isFinite(img.page) ? ` (page ${img.page})` : ''}</p>
                              </div>
                            ))}
                          </div>
                        )}
                        {msg.time && (
                          <div className="mt-2 text-2xs text-ink-muted flex items-center gap-3">
                            <span>{msg.time.toFixed(0)}ms</span>
                            {msg.confidence !== undefined && (
                              <span className="text-sky-500">置信度 {(msg.confidence * 100).toFixed(0)}%</span>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  {msg.role === 'user' && (
                    <div className="w-7 h-7 rounded-full bg-cloud-300 flex items-center justify-center shrink-0 mt-0.5">
                      <User size={14} className="text-ink-muted" />
                    </div>
                  )}
                </div>
              ))}
              {loading && activeTab === 'qa' && (
                <div className="flex gap-3">
                  <div className="w-7 h-7 rounded-full bg-sky-100 dark:bg-sky-900/40 flex items-center justify-center">
                    <Loader2 size={14} className="text-sky-500 animate-spin" />
                  </div>
                  <div className="bg-cloud-200 border border-cloud-200 rounded-2xl px-4 py-3">
                    <div className="flex gap-1.5">
                      <div className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
                      <div className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" style={{ animationDelay: '0.15s' }} />
                      <div className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" style={{ animationDelay: '0.3s' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={qaEndRef} />
            </div>

            {/* 输入区 */}
            <div className="shrink-0 flex gap-2">
              <input value={qaInput} onChange={e => setQaInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleQASend()}
                disabled={!canInteract}
                placeholder="输入制造领域问题…"
                className="flex-1 px-4 py-3 rounded-xl border border-cloud-300 text-sm bg-white
                  focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-50 transition-all" />
              {loading && activeTab === 'qa' ? (
                <button onClick={cancelQA}
                  className="btn-danger px-5 py-3 rounded-xl">
                  取消
                </button>
              ) : (
                <button onClick={() => handleQASend()} disabled={!canInteract || !qaInput.trim()}
                  className="btn-primary px-5 py-3 rounded-xl disabled:opacity-50">
                  <Send size={16} />
                </button>
              )}
            </div>
          </motion.div>
        )}

        {/* ========== 代码解析标签页 ========== */}
        {activeTab === 'code' && (
          <motion.div key="code" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex-1 min-h-0 overflow-y-auto">
            {!codeResult && (
              <div className="text-center py-8 text-ink-muted">
                <Code2 size={32} className="mx-auto mb-2 opacity-30" />
                <p className="text-sm">粘贴 OBD 故障码 (DTC)或 PLC 程序进行分析</p>
                <p className="text-xs text-ink-muted mt-1">支持 OBD 故障码 (DTC)语法高亮、指令解释与风险检测</p>
              </div>
            )}
            <GCodeEditor onParseResult={(data) => setCodeResult(data)} />
            {/* 输入输出信号（PLC） */}
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

        {/* ========== 故障诊断标签页 ========== */}
        {activeTab === 'diagnosis' && (
          <motion.div key="diagnosis" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex-1 flex flex-col min-h-0">
            {/* 消息列表 */}
            <div className="flex-1 overflow-y-auto space-y-4 pr-2 mb-4">
              {diagMessages.length === 0 && (
                <div className="text-center py-16 text-ink-muted">
                  <Wrench size={40} className="mx-auto mb-3 opacity-30" />
                  <p className="text-sm">描述设备故障现象，智能体将进行交互式诊断</p>
                  <div className="flex flex-wrap justify-center gap-2 mt-4">
                    {['发动机故障灯亮，怠速不稳', '刹车时有异响，制动距离变长', '空调压缩机不工作'].map(q => (
                      <button key={q} onClick={() => startDiagnosis(q)}
                        className="px-3 py-1.5 rounded-full text-xs bg-cloud-100 text-ink-body hover:bg-sky-50 hover:text-sky-600 transition-colors">
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
                      : 'bg-cloud-200 border border-cloud-200'
                  }`}>
                    {msg.role === 'user' ? (
                      <p className="text-sm">{msg.content}</p>
                    ) : (
                      <div className="text-sm text-ink-body">
                        {msg.isFinal ? (
                          <ReactMarkdown components={markdownComponents}>{msg.content}</ReactMarkdown>
                        ) : (
                          <>
                            <p>{msg.content}</p>
                            {msg.initial_matches !== undefined && (
                              <p className="text-xs text-ink-muted mt-1">匹配到 {msg.initial_matches} 个相似案例</p>
                            )}
                            {msg.confidence !== undefined && (
                              <p className="text-xs text-ink-muted mt-1">当前置信度 {(msg.confidence * 100).toFixed(0)}%</p>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  {msg.role === 'user' && (
                    <div className="w-7 h-7 rounded-full bg-cloud-300 flex items-center justify-center shrink-0 mt-0.5">
                      <User size={14} className="text-ink-muted" />
                    </div>
                  )}
                </div>
              ))}
              {/* 当前诊断的快捷回复按钮 */}
              {diagSession && !loading && (
                <div className="flex flex-wrap gap-2 pl-10">
                  {(() => {
                    // 优先使用后端建议回复，不存在时回退到默认回复
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
                  <div className="bg-cloud-200 border border-cloud-200 rounded-2xl px-4 py-3">
                    <div className="flex gap-1.5">
                      <div className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
                      <div className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" style={{ animationDelay: '0.15s' }} />
                      <div className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" style={{ animationDelay: '0.3s' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={diagEndRef} />
            </div>

            {/* 输入区：始终可见，便于用户输入自定义回复 */}
            <div className="shrink-0 flex gap-2">
              <textarea value={diagInput} onChange={e => setDiagInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    diagSession ? continueDiagnosis(diagInput) : startDiagnosis()
                  }
                }}
                placeholder={diagSession ? '回答诊断问题或输入补充信息…' : '描述车辆故障现象…'}
                disabled={!canInteract}
                rows={2}
                className="flex-1 px-4 py-3 rounded-xl border border-cloud-300 text-sm bg-white resize-none
                  focus:outline-none focus:border-amber-300 focus:ring-2 focus:ring-amber-50 transition-all" />
              <button onClick={() => diagSession ? continueDiagnosis(diagInput) : startDiagnosis()}
                disabled={!canInteract || loading || !diagInput.trim()}
                className="btn-primary px-5 py-3 rounded-xl disabled:opacity-50 bg-amber-500 hover:bg-amber-600">
                <Send size={16} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
    </ManufacturingAgentErrorBoundary>
  )
}
