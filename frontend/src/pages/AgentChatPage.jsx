import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Send, User, Bot, Clock, Plus, Trash2, Edit3, X, ChevronLeft,
  ChevronDown, ChevronRight, Brain, Zap, MessageSquare, ArrowLeft,
  Settings2, Layers, Cpu, Database, Check, GitGraph
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { motion, AnimatePresence } from 'framer-motion'
import { api, getToken } from '../utils/api'

const MODES = [
  { key: 'rrf', icon: Brain, label: '融合' },
  { key: 'graph', icon: GitGraph, label: '图谱' },
  { key: 'hybrid', icon: Layers, label: '智能' },
  { key: 'local', icon: Zap, label: '精确' },
  { key: 'global', icon: Brain, label: '全局' },
  { key: 'naive', icon: MessageSquare, label: '快速' },
]

const REASONING_MODES = [
  { key: 'none', icon: Zap, label: '普通' },
  { key: 'react', icon: Brain, label: 'ReAct' },
  { key: 'cot', icon: Layers, label: 'CoT' },
]

// Warm theme markdown components
const markdownComponents = {
  h2: ({ children, ...props }) => <h2 className="text-base font-semibold text-warm-800 mt-5 mb-2 pb-1.5 border-b border-warm-200" {...props}>{children}</h2>,
  h3: ({ children, ...props }) => <h3 className="text-sm font-semibold text-warm-700 mt-4 mb-1.5" {...props}>{children}</h3>,
  p: ({ children, ...props }) => <p className="text-sm text-warm-600 leading-relaxed my-2" {...props}>{children}</p>,
  strong: ({ children, ...props }) => <strong className="font-semibold text-coral-600" {...props}>{children}</strong>,
  ul: ({ children, ...props }) => <ul className="text-sm text-warm-600 space-y-1 my-2 pl-4" {...props}>{children}</ul>,
  ol: ({ children, ...props }) => <ol className="text-sm text-warm-600 space-y-1 my-2 pl-4 list-decimal" {...props}>{children}</ol>,
  li: ({ children, ...props }) => <li className="text-sm text-warm-600" {...props}>{children}</li>,
  code: ({ inline, className, children, ...props }) => {
    const match = /language-(\w+)/.exec(className || '')
    return !inline ? (
      <div className="my-3 rounded-xl border border-warm-200 overflow-hidden">
        <div className="bg-warm-100 px-3 py-1 text-[10px] text-warm-500 font-mono">{match ? match[1] : 'code'}</div>
        <pre className="bg-warm-50 p-3 overflow-x-auto text-xs"><code className={className} {...props}>{children}</code></pre>
      </div>
    ) : (
      <code className="px-1.5 py-0.5 rounded-md text-xs font-mono bg-warm-100 text-amber-700" {...props}>{children}</code>
    )
  },
  table: ({ children, ...props }) => <div className="my-3 overflow-x-auto"><table className="min-w-full text-xs border-collapse" {...props}>{children}</table></div>,
  thead: ({ children, ...props }) => <thead className="bg-warm-50" {...props}>{children}</thead>,
  th: ({ children, ...props }) => <th className="border border-warm-200 px-3 py-1.5 text-left text-warm-700 font-medium" {...props}>{children}</th>,
  td: ({ children, ...props }) => <td className="border border-warm-200 px-3 py-1.5 text-warm-500" {...props}>{children}</td>,
  blockquote: ({ children, ...props }) => <blockquote className="border-l-3 border-coral-300 pl-3 my-2 text-warm-500 italic text-xs" {...props}>{children}</blockquote>,
  hr: (props) => <hr className="my-4 border-warm-200" {...props} />,
  a: ({ children, href, ...props }) => <a href={href} className="text-coral-500 underline underline-offset-2 hover:text-coral-600" target="_blank" rel="noopener" {...props}>{children}</a>,
  em: ({ children, ...props }) => <em className="italic text-warm-700" {...props}>{children}</em>,
}

export default function AgentChatPage() {
  const { id: agentId } = useParams()
  const navigate = useNavigate()
  const chatRef = useRef()
  const abortRef = useRef(null)

  const [agent, setAgent] = useState(null)
  const [threads, setThreads] = useState([])
  const [activeThreadId, setActiveThreadId] = useState('')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [mode, setMode] = useState('')
  const [agentMode, setAgentMode] = useState('none')
  const [loading, setLoading] = useState(false)
  const [expandedThinking, setExpandedThinking] = useState({})
  const [renamingThread, setRenamingThread] = useState(null)
  const [renameTitle, setRenameTitle] = useState('')

  useEffect(() => {
    api.listAgents().then(r => {
      const a = (r.agents || []).find(x => x.id === agentId)
      if (a) {
        setAgent(a)
        setMode(a.query_mode || 'hybrid')
        setAgentMode(a.agent_mode || 'none')
      }
    }).catch(e => console.warn('[AgentChat] Failed to load agent:', e.message))
    loadThreads(true)
  }, [agentId])

  const loadThreads = (autoSelect = false) => {
    api.listConversations(agentId).then(r => {
      setThreads(r.threads || [])
      if (r.threads?.length > 0 && autoSelect) {
        loadThread(r.threads[0].id)
      }
    }).catch(e => console.warn('[AgentChat] Failed to load conversations:', e.message))
  }

  const loadThread = (threadId) => {
    setActiveThreadId(threadId)
    const t = threads.find(x => x.id === threadId)
    if (t?.messages) {
      setMessages(t.messages.map((m, i) => ({
        ...m, id: `${threadId}-${i}`, thinking: [], thinkingDone: true, done: true,
      })))
    } else {
      setMessages([])
    }
    api.listConversations(agentId).then(r => {
      const updated = (r.threads || []).find(x => x.id === threadId)
      if (updated?.messages) {
        setThreads(r.threads || [])
        setMessages(updated.messages.map((m, i) => ({
          ...m, id: `${threadId}-${i}`, thinking: [], thinkingDone: true, done: true,
        })))
      }
    }).catch(e => console.warn('[AgentChat] Failed to load thread messages:', e.message))
  }

  const createThread = async () => {
    const res = await api.createConversation(agentId, '新对话')
    setActiveThreadId(res.thread.id)
    setMessages([])
  }

  const deleteThread = async (threadId) => {
    await api.deleteConversation(agentId, threadId)
    if (activeThreadId === threadId) { setActiveThreadId(''); setMessages([]) }
    loadThreads()
  }

  const renameThread = async () => {
    if (!renameTitle.trim()) return
    await api.updateConversation(agentId, renamingThread, renameTitle)
    setRenamingThread(null)
    loadThreads()
  }

  const handleSSEEvent = (msgId, event) => {
    const { type, content, id: resultId, elapsed, images } = event
    switch (type) {
      case 'thinking':
        // 结构化 thinking（ReAct/CoT: {step, thought, action, observation}）
        if (event.thought) {
          setMessages(prev => prev.map(m =>
            m.id === msgId ? { ...m, thinking: [...(m.thinking || []), {
              step: event.step,
              thought: event.thought,
              action: event.action || '',
              observation: event.observation || '',
              elapsed_ms: event.elapsed_ms || 0,
            }]} : m
          ))
        } else if (content) {
          // 普通模式 thinking 字符串
          setMessages(prev => prev.map(m =>
            m.id === msgId ? { ...m, thinking: [...(m.thinking || []), content] } : m
          ))
        }
        break
      case 'token':
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, content: m.content + content } : m
        ))
        break
      case 'done':
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, done: true, thinkingDone: true, elapsed, images: images || [] } : m
        ))
        setTimeout(() => setExpandedThinking(prev => ({ ...prev, [msgId]: false })), 2000)
        setLoading(false)
        abortRef.current = null
        loadThreads()
        break
      case 'error':
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, content: `❌ ${content}`, done: true, error: true } : m
        ))
        setLoading(false)
        abortRef.current = null
        break
      case 'agent_info': break
    }
  }

  const streamQuery = useCallback(async (query) => {
    const controller = new AbortController()
    abortRef.current = controller

    const msgId = Date.now().toString()
    setMessages(prev => [...prev, {
      id: msgId, role: 'assistant', content: '',
      thinking: [], thinkingDone: false, done: false, elapsed: null,
    }])
    setExpandedThinking(prev => ({ ...prev, [msgId]: true }))

    try {
      let headers = { 'Content-Type': 'application/json' }
      try { const t = JSON.parse(localStorage.getItem('raganything_auth') || '{}').token; if (t) headers['Authorization'] = `Bearer ${t}` } catch {}
      const res = await fetch(`/api/agents/${agentId}/query/stream`, {
        method: 'POST', headers,
        body: JSON.stringify({ query, thread_id: activeThreadId, mode, agent_mode: agentMode }),
        signal: controller.signal,
      })

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
          try { handleSSEEvent(msgId, JSON.parse(line.slice(6))) } catch (parseErr) {
            console.warn('[AgentChat] SSE parse error:', parseErr.message, 'line:', line.slice(0, 100))
          }
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, content: m.content || '⏹️ 已取消', done: true } : m
        ))
      } else {
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, content: `❌ 错误: ${e.message}`, done: true, error: true } : m
        ))
      }
      setLoading(false)
      abortRef.current = null
    }
  }, [agentId, activeThreadId, mode, agentMode])

  const send = async () => {
    if (!input.trim() || loading) return
    if (!activeThreadId) await createThread()
    const q = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: q }])
    setLoading(true)
    await streamQuery(q)
  }

  const cancelQuery = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setLoading(false)
    }
  }

  const toggleThinking = (msgId) => {
    setExpandedThinking(prev => ({ ...prev, [msgId]: !prev[msgId] }))
  }

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  // Abort streaming on unmount to prevent reader leaks
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
      }
    }
  }, [])

  if (!agent) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="w-8 h-8 mx-auto mb-3 rounded-full border-2 border-coral-300 border-t-coral-500 animate-spin" />
          <p className="text-warm-500 text-xs">正在加载智能体…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-3" style={{ height: 'calc(100vh - 7rem)' }}>
      {/* Thread Sidebar */}
      <div className="w-56 card p-3 space-y-2 shrink-0 overflow-y-auto flex flex-col">
        <div className="pb-3 border-b border-warm-100">
          <button onClick={() => navigate('/agents')} className="flex items-center gap-1 text-xs text-warm-500 hover:text-warm-600 mb-2 transition-colors">
            <ArrowLeft size={12} /> 返回智能体列表
          </button>
          <div className="flex items-center gap-2">
            <span className="text-2xl">{agent.icon || '🤖'}</span>
            <div className="min-w-0">
              <p className="text-sm font-medium text-warm-700 truncate">{agent.name}</p>
              <p className="text-[10px] text-warm-500">{agent.kb_name} · {agent.llm_model}</p>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-[10px] text-warm-500 uppercase tracking-wider">对话线程</span>
          <button onClick={createThread} className="text-warm-500 hover:text-coral-500 transition-colors">
            <Plus size={14} />
          </button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto">
          {threads.map(t => (
            <div key={t.id}
              className={`group flex items-center gap-1 px-2 py-1.5 rounded-xl text-xs cursor-pointer transition-colors ${
                activeThreadId === t.id
                  ? 'bg-coral-50 text-coral-600 border border-coral-200'
                  : 'text-warm-500 hover:text-warm-700 hover:bg-warm-50'
              }`}
              onClick={() => loadThread(t.id)}
            >
              {renamingThread === t.id ? (
                <input className="input-field flex-1 text-[11px] py-0.5" value={renameTitle}
                  onChange={e => setRenameTitle(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') renameThread(); if (e.key === 'Escape') setRenamingThread(null) }}
                  onClick={e => e.stopPropagation()} autoFocus />
              ) : (
                <>
                  <span className="flex-1 truncate">{t.title}</span>
                  <span className="text-[9px] text-warm-500 font-mono opacity-0 group-hover:opacity-100">{t.updated_at?.slice(11, 16)}</span>
                  <button className="opacity-0 group-hover:opacity-100 p-0.5 text-warm-500 hover:text-warm-600"
                    onClick={e => { e.stopPropagation(); setRenamingThread(t.id); setRenameTitle(t.title) }}>
                    <Edit3 size={10} />
                  </button>
                  <button className="opacity-0 group-hover:opacity-100 p-0.5 text-warm-500 hover:text-rose-500"
                    onClick={e => { e.stopPropagation(); deleteThread(t.id) }}>
                    <Trash2 size={10} />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
        {threads.length === 0 && (
          <div className="text-center py-6">
            <p className="text-xs text-warm-500">还没有对话</p>
            <p className="text-[10px] text-warm-400 mt-1">发送第一条消息开始 ✨</p>
          </div>
        )}

        <div className="pt-3 border-t border-warm-100 space-y-1">
          <p className="text-[10px] text-warm-500 flex items-center gap-1"><Database size={10}/> {agent.kb_name}</p>
          <p className="text-[10px] text-warm-500 flex items-center gap-1"><Cpu size={10}/> {agent.llm_model}</p>
        </div>
      </div>

      {/* Main Chat */}
      <div className="flex-1 flex flex-col card p-0 overflow-hidden">
        <div className="p-3 border-b border-warm-200/60 flex items-center gap-3 shrink-0">
          <span className="text-xl">{agent.icon || '🤖'}</span>
          <div className="flex-1 min-w-0">
            <h2 className="font-display text-sm font-semibold text-warm-800 truncate">{agent.name}</h2>
            <p className="text-[10px] text-warm-500 truncate">{agent.welcome_message || agent.description}</p>
          </div>
          <div className="flex items-center gap-2">
            {/* 检索模式 */}
            <div className="flex gap-1">
              {MODES.map(({ key, icon: Icon, label }) => (
                <button key={key}
                  onClick={() => setMode(key)}
                  className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium transition-all ${
                    mode === key
                      ? 'bg-coral-50 text-coral-600 border border-coral-200'
                      : 'text-warm-500 hover:text-warm-600'
                  }`}
                >
                  <Icon size={11} /> {label}
                </button>
              ))}
            </div>
            {/* 分隔符 */}
            <div className="w-px h-5 bg-warm-300" />
            {/* 推理模式 */}
            <div className="flex gap-1">
              {REASONING_MODES.map(({ key, icon: Icon, label }) => (
                <button key={key}
                  onClick={() => setAgentMode(key)}
                  className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium transition-all ${
                    agentMode === key
                      ? 'bg-sage-50 text-sage-600 border border-sage-200'
                      : 'text-warm-500 hover:text-warm-600'
                  }`}
                >
                  <Icon size={11} /> {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div ref={chatRef} className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full">
              <span className="text-5xl mb-3">{agent.icon || '🤖'}</span>
              <p className="text-sm text-warm-500">{agent.welcome_message || '你好！有什么可以帮你的？'}</p>
            </div>
          )}
          {messages.map((m, i) => {
            if (m.role === 'user') {
              return (
                <div key={i} className="flex gap-3 flex-row-reverse">
                  <div className="w-7 h-7 rounded-xl flex items-center justify-center shrink-0 bg-coral-50 text-coral-500">
                    <User size={13} />
                  </div>
                  <div className="max-w-[80%] rounded-2xl rounded-tr-md px-4 py-2.5 text-sm bg-coral-50 border border-coral-200 text-warm-700">
                    <div className="whitespace-pre-wrap">{m.content}</div>
                  </div>
                </div>
              )
            }
            const hasThinking = m.thinking?.length > 0
            // 推理进行中时强制展开，完成后允许折叠
            const isExpanded = !m.thinkingDone || expandedThinking[m.id] !== false
            const showTypingCursor = !m.done && m.content?.length > 0
            return (
              <div key={i} className="flex gap-3">
                <span className="text-xl shrink-0 mt-0.5">{agent.icon || '🤖'}</span>
                <div className="max-w-[80%] min-w-[40%]">
                  {hasThinking && (
                    <div className="mb-2 rounded-xl border border-warm-200 bg-warm-50 overflow-hidden">
                      <button onClick={() => toggleThinking(m.id)}
                        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-warm-500 hover:text-warm-700">
                        {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                        <Brain size={12} className="text-purple-500" />
                        <span>思考过程</span>
                        {m.thinkingDone ? <span className="ml-auto text-[9px] text-sage-500">完成 ✓</span>
                          : <Zap size={9} className="ml-auto text-amber-500 animate-pulse" />}
                        <span className="text-[9px] text-warm-500 ml-1">{m.thinking.length} 步</span>
                      </button>
                      {isExpanded && (
                        <div className="border-t border-warm-200/50 px-3 py-2 space-y-2 max-h-96 overflow-y-auto">
                          {m.thinking.map((step, j) => (
                            typeof step === 'object' ? (
                              <div key={j} className="text-[10px] space-y-0.5">
                                <div className="flex items-start gap-1.5">
                                  <span className="shrink-0 mt-0.5">🧠</span>
                                  <span className="text-warm-600">{step.thought}</span>
                                </div>
                                {step.action && (
                                  <div className="flex items-start gap-1.5 ml-1">
                                    <span className="shrink-0 mt-0.5">🔧</span>
                                    <span className="text-sky-500 font-medium">{step.action}</span>
                                  </div>
                                )}
                                {step.observation && (
                                  <div className="flex items-start gap-1.5 ml-1">
                                    <span className="shrink-0 mt-0.5">📋</span>
                                    <span className="text-sage-500 whitespace-pre-wrap break-all">{step.observation}</span>
                                  </div>
                                )}
                                {step.elapsed_ms > 0 && (
                                  <div className="text-[9px] text-warm-400 ml-4.5">{(step.elapsed_ms / 1000).toFixed(2)}s</div>
                                )}
                              </div>
                            ) : (
                              <div key={j} className="text-[10px] text-warm-500 font-mono flex items-start gap-1.5">
                                <span className="text-warm-400 shrink-0 mt-0.5">▸</span><span>{step}</span>
                              </div>
                            )
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  <div className={`rounded-2xl rounded-tl-md px-4 py-3 text-sm leading-relaxed ${
                    m.error ? 'bg-rose-50 border border-rose-200 text-rose-700'
                      : 'bg-warm-50 border border-warm-200 text-warm-700'
                  }`}>
                    <div className="markdown-content">
                      <ReactMarkdown components={markdownComponents}>{m.content}</ReactMarkdown>
                      {showTypingCursor && <span className="inline-block w-1.5 h-4 bg-coral-500 ml-0.5 animate-pulse align-middle rounded-sm" />}
                    </div>
                    {m.images && m.images.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-warm-200">
                        <p className="text-[10px] text-warm-500 mb-2">📷 引用的图片 ({m.images.length})</p>
                        <div className="grid grid-cols-2 gap-2">
                          {m.images.map((img, i) => {
                            const token = getToken()
                            const imgUrl = `/api/files/image?path=${encodeURIComponent(img)}${token ? '&token=' + encodeURIComponent(token) : ''}`
                            return (
                            <a key={i} href={imgUrl} target="_blank" rel="noopener" className="block">
                              <img
                                src={imgUrl}
                                alt={`引用图片 ${i + 1}`}
                                className="w-full h-32 object-cover rounded-xl border border-warm-200 hover:border-coral-300 transition-colors"
                                loading="lazy"
                              />
                            </a>
                            )
                          })}
                        </div>
                      </div>
                    )}
                    {m.elapsed && <p className="text-[10px] text-warm-500 mt-1.5 font-mono">{m.elapsed}s</p>}
                  </div>
                </div>
              </div>
            )
          })}
          {loading && !messages.some(m => m.role === 'assistant' && !m.done) && (
            <div className="flex gap-3">
              <span className="text-xl">{agent.icon || '🤖'}</span>
              <div className="bg-warm-50 rounded-xl px-4 py-3 flex items-center gap-2 border border-warm-200">
                <div className="flex gap-1">
                  <span className="w-1.5 h-1.5 bg-coral-400 rounded-full animate-pulse" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 bg-coral-400 rounded-full animate-pulse" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 bg-coral-400 rounded-full animate-pulse" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="p-3 border-t border-warm-200/60 shrink-0">
          <div className="flex gap-2">
            <input className="input-field flex-1 text-sm" placeholder={`向 ${agent.name} 提问...`} value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) send()
                if (e.key === 'Escape') cancelQuery()
              }} />
            {loading ? (
              <button className="btn-danger flex items-center gap-2 text-sm" onClick={cancelQuery}>
                取消
              </button>
            ) : (
              <button className="btn-primary flex items-center gap-2 text-sm" onClick={send}>
                <Send size={14} /> 发送
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
