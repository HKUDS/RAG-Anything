import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Send, User, Bot, Clock, Plus, Trash2, Edit3, X, ChevronLeft,
  ChevronDown, ChevronRight, Brain, Zap, MessageSquare, ArrowLeft,
  Settings2, Layers, Cpu, Database, Check
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '../utils/api'

const MODES = [
  { key: 'hybrid', icon: Layers, label: '智能' },
  { key: 'local', icon: Zap, label: '精确' },
  { key: 'global', icon: Brain, label: '全局' },
  { key: 'naive', icon: MessageSquare, label: '快速' },
]

// Dark theme markdown components (same as QueryPage)
const markdownComponents = {
  h2: ({ children, ...props }) => <h2 className="text-base font-bold text-slate-100 mt-5 mb-2 pb-1.5 border-b border-slate-700/50" {...props}>{children}</h2>,
  h3: ({ children, ...props }) => <h3 className="text-sm font-semibold text-slate-200 mt-4 mb-1.5" {...props}>{children}</h3>,
  p: ({ children, ...props }) => <p className="text-sm text-slate-300 leading-relaxed my-2" {...props}>{children}</p>,
  strong: ({ children, ...props }) => <strong className="font-semibold text-neon-300" {...props}>{children}</strong>,
  ul: ({ children, ...props }) => <ul className="text-sm text-slate-300 space-y-1 my-2 pl-4" {...props}>{children}</ul>,
  ol: ({ children, ...props }) => <ol className="text-sm text-slate-300 space-y-1 my-2 pl-4 list-decimal" {...props}>{children}</ol>,
  li: ({ children, ...props }) => <li className="text-sm text-slate-300" {...props}>{children}</li>,
  code: ({ inline, className, children, ...props }) => {
    const match = /language-(\w+)/.exec(className || '')
    return !inline ? (
      <div className="my-3 rounded-lg border border-slate-700 overflow-hidden">
        <div className="bg-slate-800 px-3 py-1 text-[10px] text-slate-500 font-mono">{match ? match[1] : 'code'}</div>
        <pre className="bg-ink-900/80 p-3 overflow-x-auto text-xs"><code className={className} {...props}>{children}</code></pre>
      </div>
    ) : (
      <code className="px-1 py-0.5 rounded text-xs font-mono bg-slate-800 text-amber-300" {...props}>{children}</code>
    )
  },
  table: ({ children, ...props }) => <div className="my-3 overflow-x-auto"><table className="min-w-full text-xs border-collapse" {...props}>{children}</table></div>,
  thead: ({ children, ...props }) => <thead className="bg-slate-800/50" {...props}>{children}</thead>,
  th: ({ children, ...props }) => <th className="border border-slate-700 px-3 py-1.5 text-left text-slate-300 font-medium" {...props}>{children}</th>,
  td: ({ children, ...props }) => <td className="border border-slate-700 px-3 py-1.5 text-slate-400" {...props}>{children}</td>,
  blockquote: ({ children, ...props }) => <blockquote className="border-l-2 border-neon-500/40 pl-3 my-2 text-slate-400 italic text-xs" {...props}>{children}</blockquote>,
  hr: (props) => <hr className="my-4 border-slate-700/50" {...props} />,
  a: ({ children, href, ...props }) => <a href={href} className="text-neon-400 underline underline-offset-2 hover:text-neon-300" target="_blank" rel="noopener" {...props}>{children}</a>,
  em: ({ children, ...props }) => <em className="italic text-slate-200" {...props}>{children}</em>,
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
  const [loading, setLoading] = useState(false)
  const [expandedThinking, setExpandedThinking] = useState({})
  const [renamingThread, setRenamingThread] = useState(null)
  const [renameTitle, setRenameTitle] = useState('')

  // Load agent and conversations
  useEffect(() => {
    api.listAgents().then(r => {
      const a = (r.agents || []).find(x => x.id === agentId)
      if (a) {
        setAgent(a)
        setMode(a.query_mode || 'hybrid')
      }
    }).catch(() => {})

    loadThreads()
  }, [agentId])

  const loadThreads = () => {
    api.listConversations(agentId).then(r => {
      setThreads(r.threads || [])
      if (r.threads?.length > 0 && !activeThreadId) {
        loadThread(r.threads[0].id)
      }
    }).catch(() => {})
  }

  const loadThread = (threadId) => {
    setActiveThreadId(threadId)
    // Find thread messages from the loaded threads
    const t = threads.find(x => x.id === threadId)
    if (t?.messages) {
      setMessages(t.messages.map((m, i) => ({
        ...m,
        id: `${threadId}-${i}`,
        thinking: [],
        thinkingDone: true,
        done: true,
      })))
    } else {
      setMessages([])
    }
    // Reload to get latest
    api.listConversations(agentId).then(r => {
      const updated = (r.threads || []).find(x => x.id === threadId)
      if (updated?.messages) {
        setThreads(r.threads || [])
        setMessages(updated.messages.map((m, i) => ({
          ...m,
          id: `${threadId}-${i}`,
          thinking: [],
          thinkingDone: true,
          done: true,
        })))
      }
    }).catch(() => {})
  }

  const createThread = async () => {
    const res = await api.createConversation(agentId, '新对话')
    loadThreads()
    setActiveThreadId(res.thread.id)
    setMessages([])
  }

  const deleteThread = async (threadId) => {
    await api.deleteConversation(agentId, threadId)
    if (activeThreadId === threadId) {
      setActiveThreadId('')
      setMessages([])
    }
    loadThreads()
  }

  const renameThread = async () => {
    if (!renameTitle.trim()) return
    await api.updateConversation(agentId, renamingThread, renameTitle)
    setRenamingThread(null)
    loadThreads()
  }

  // SSE streaming
  const handleSSEEvent = (msgId, event) => {
    const { type, content, id: resultId, elapsed } = event
    switch (type) {
      case 'thinking':
        if (content) {
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
          m.id === msgId ? { ...m, done: true, thinkingDone: true, elapsed } : m
        ))
        setTimeout(() => setExpandedThinking(prev => ({ ...prev, [msgId]: false })), 2000)
        setLoading(false)
        abortRef.current = null
        loadThreads() // Refresh thread list
        break
      case 'error':
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, content: `❌ ${content}`, done: true, error: true } : m
        ))
        setLoading(false)
        abortRef.current = null
        break
      case 'agent_info':
        // Agent info confirmed
        break
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
      const res = await fetch(`/api/agents/${agentId}/query/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, thread_id: activeThreadId, mode }),
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
          try { handleSSEEvent(msgId, JSON.parse(line.slice(6))) } catch {}
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
  }, [agentId, activeThreadId, mode])

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

  if (!agent) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500">加载中...</p>
      </div>
    )
  }

  return (
    <div className="flex gap-3" style={{ height: 'calc(100vh - 8rem)' }}>
      {/* Thread Sidebar */}
      <div className="w-56 glass p-3 space-y-2 shrink-0 overflow-y-auto flex flex-col">
        {/* Agent info */}
        <div className="pb-3 border-b border-slate-700/50">
          <button onClick={() => navigate('/agents')} className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 mb-2">
            <ArrowLeft size={12} /> 返回智能体列表
          </button>
          <div className="flex items-center gap-2">
            <span className="text-2xl">{agent.icon || '🤖'}</span>
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-200 truncate">{agent.name}</p>
              <p className="text-[10px] text-slate-500">{agent.kb_name} · {agent.llm_model}</p>
            </div>
          </div>
        </div>

        {/* Thread list */}
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-slate-500 uppercase tracking-wider">对话线程</span>
          <button onClick={createThread} className="text-slate-500 hover:text-neon-400">
            <Plus size={14} />
          </button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto">
          {threads.map(t => (
            <div key={t.id}
              className={`group flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs cursor-pointer transition-colors ${
                activeThreadId === t.id
                  ? 'bg-neon-500/10 text-neon-400 border border-neon-500/20'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
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
                  <span className="text-[9px] text-slate-600 font-mono opacity-0 group-hover:opacity-100">{t.updated_at?.slice(11, 16)}</span>
                  <button className="opacity-0 group-hover:opacity-100 p-0.5 text-slate-600 hover:text-slate-400"
                    onClick={e => { e.stopPropagation(); setRenamingThread(t.id); setRenameTitle(t.title) }}>
                    <Edit3 size={10} />
                  </button>
                  <button className="opacity-0 group-hover:opacity-100 p-0.5 text-slate-600 hover:text-red-400"
                    onClick={e => { e.stopPropagation(); deleteThread(t.id) }}>
                    <Trash2 size={10} />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
        {threads.length === 0 && (
          <p className="text-xs text-slate-600 text-center py-4">暂无对话，发送第一条消息开始</p>
        )}

        {/* Agent config summary */}
        <div className="pt-3 border-t border-slate-700/50 space-y-1">
          <p className="text-[10px] text-slate-600 flex items-center gap-1"><Database size={10}/> {agent.kb_name}</p>
          <p className="text-[10px] text-slate-600 flex items-center gap-1"><Cpu size={10}/> {agent.llm_model}</p>
        </div>
      </div>

      {/* Main Chat */}
      <div className="flex-1 flex flex-col glass p-0 overflow-hidden">
        {/* Header */}
        <div className="p-3 border-b border-slate-700/50 flex items-center gap-3 shrink-0">
          <span className="text-xl">{agent.icon || '🤖'}</span>
          <div className="flex-1 min-w-0">
            <h2 className="font-display text-sm font-bold text-slate-100 truncate">{agent.name}</h2>
            <p className="text-[10px] text-slate-500 truncate">{agent.welcome_message || agent.description}</p>
          </div>
          <div className="flex gap-1">
            {MODES.map(({ key, icon: Icon, label }) => (
              <button key={key}
                onClick={() => setMode(key)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-all ${
                  mode === key
                    ? 'bg-neon-500/10 text-neon-400 border border-neon-500/20'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                <Icon size={11} /> {label}
              </button>
            ))}
          </div>
        </div>

        {/* Messages */}
        <div ref={chatRef} className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-slate-600">
              <span className="text-5xl mb-3">{agent.icon || '🤖'}</span>
              <p className="text-sm">{agent.welcome_message || '你好！有什么可以帮你的？'}</p>
            </div>
          )}
          {messages.map((m, i) => {
            if (m.role === 'user') {
              return (
                <div key={i} className="flex gap-3 flex-row-reverse">
                  <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 bg-neon-500/20 text-neon-400">
                    <User size={13} />
                  </div>
                  <div className="max-w-[80%] rounded-xl px-4 py-2.5 text-sm bg-neon-500/10 border border-neon-500/20 text-slate-200">
                    <div className="whitespace-pre-wrap">{m.content}</div>
                  </div>
                </div>
              )
            }
            // AI message
            const hasThinking = m.thinking?.length > 0
            const isExpanded = expandedThinking[m.id] !== false
            const showTypingCursor = !m.done && m.content?.length > 0
            return (
              <div key={i} className="flex gap-3">
                <span className="text-xl shrink-0 mt-0.5">{agent.icon || '🤖'}</span>
                <div className="max-w-[80%] min-w-[40%]">
                  {hasThinking && (
                    <div className="mb-2 rounded-lg border border-slate-700/50 bg-ink-800/50 overflow-hidden">
                      <button onClick={() => toggleThinking(m.id)}
                        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-500 hover:text-slate-300">
                        {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                        <Brain size={12} className="text-purple-400" />
                        <span>思考过程</span>
                        {m.thinkingDone ? <span className="ml-auto text-[9px] text-emerald-400">完成</span>
                          : <Zap size={9} className="ml-auto text-amber-400 animate-pulse" />}
                        <span className="text-[9px] text-slate-600 ml-1">{m.thinking.length} 步</span>
                      </button>
                      {isExpanded && (
                        <div className="border-t border-slate-700/30 px-3 py-2 space-y-0.5 max-h-40 overflow-y-auto">
                          {m.thinking.map((step, j) => (
                            <div key={j} className="text-[10px] text-slate-500 font-mono flex items-start gap-1.5">
                              <span className="text-slate-700 shrink-0 mt-0.5">▸</span><span>{step}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  <div className={`rounded-xl px-4 py-3 text-sm leading-relaxed ${
                    m.error ? 'bg-red-500/10 border border-red-500/20 text-red-300'
                      : 'bg-ink-700 border border-slate-700 text-slate-300'
                  }`}>
                    <div className="markdown-content">
                      <ReactMarkdown components={markdownComponents}>{m.content}</ReactMarkdown>
                      {showTypingCursor && <span className="inline-block w-1.5 h-4 bg-neon-400 ml-0.5 animate-pulse align-middle" />}
                    </div>
                    {m.elapsed && <p className="text-[10px] text-slate-600 mt-1.5 font-mono">{m.elapsed}s</p>}
                  </div>
                </div>
              </div>
            )
          })}
          {loading && !messages.some(m => m.role === 'assistant' && !m.done) && (
            <div className="flex gap-3">
              <span className="text-xl">{agent.icon || '🤖'}</span>
              <div className="bg-ink-700 rounded-xl px-4 py-3 flex items-center gap-2">
                <div className="flex gap-1">
                  <span className="w-1.5 h-1.5 bg-neon-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 bg-neon-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 bg-neon-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="p-3 border-t border-slate-700/50 shrink-0">
          <div className="flex gap-2">
            <input className="input-field flex-1 text-sm" placeholder={`向 ${agent.name} 提问...`} value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) send()
                if (e.key === 'Escape') cancelQuery()
              }} />
            {loading ? (
              <button className="btn-primary flex items-center gap-2 bg-red-500/20 border-red-500/30 text-red-400 hover:bg-red-500/30 text-sm" onClick={cancelQuery}>
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
