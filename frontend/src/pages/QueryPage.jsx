import { useState, useEffect, useRef, useCallback } from 'react'
import { Send, User, Bot, Clock, Globe, Search, FileText, Layers, History, MessageSquare, Brain, ChevronDown, ChevronRight, Zap } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { api, getCurrentKB } from '../utils/api'

const MODES = [
  { key: 'hybrid', icon: Layers, label: '智能', desc: '图谱+向量混合，推荐' },
  { key: 'local', icon: Search, label: '精确', desc: '实体关系精准查找' },
  { key: 'global', icon: Globe, label: '全局', desc: '文档整体摘要理解' },
  { key: 'naive', icon: FileText, label: '快速', desc: '纯文字匹配，速度快' },
]

// Warm theme Markdown components
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

export default function QueryPage() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState([])
  const [expandedThinking, setExpandedThinking] = useState({})
  const chatRef = useRef()
  const abortRef = useRef(null)

  useEffect(() => {
    api.getQueryHistory(20).then(r => setHistory(r.history || [])).catch(() => {})
  }, [loading])

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' })
  }, [loading])

  const streamQuery = useCallback(async (query, modeVal) => {
    const kb = getCurrentKB()
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
      const res = await fetch(`/api/query/stream?kb=${kb}`, {
        method: 'POST', headers,
        body: JSON.stringify({ query, mode: modeVal }),
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
  }, [])

  const handleSSEEvent = (msgId, event) => {
    const { type, content, id: resultId, elapsed, images } = event
    switch (type) {
      case 'thinking':
        if (content) {
          setMessages(prev => prev.map(m =>
            m.id === msgId ? { ...m, thinking: [...m.thinking, content] } : m
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
        break
      case 'error':
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, content: `❌ ${content}`, done: true, error: true } : m
        ))
        setLoading(false)
        abortRef.current = null
        break
    }
  }

  const send = async () => {
    if (!input.trim() || loading) return
    const q = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: q }])
    setLoading(true)
    await streamQuery(q, mode)
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

  const loadHistory = (item) => {
    setMessages([
      { role: 'user', content: item.query },
      {
        id: `hist-${item.id}`, role: 'assistant',
        content: item.answer, thinking: [], thinkingDone: true,
        done: true, elapsed: item.elapsed,
      },
    ])
    setMode(item.mode)
  }

  const renderMessage = (m, i) => {
    if (m.role === 'user') {
      return (
        <div key={i} className="flex gap-3 flex-row-reverse">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 bg-coral-50 text-coral-500">
            <User size={16} />
          </div>
          <div className="max-w-[80%] rounded-2xl rounded-tr-md px-4 py-3 text-sm leading-relaxed bg-coral-50 border border-coral-200 text-warm-700">
            <div className="whitespace-pre-wrap">{m.content}</div>
          </div>
        </div>
      )
    }

    const hasThinking = m.thinking && m.thinking.length > 0
    const isExpanded = expandedThinking[m.id] !== false
    const showTypingCursor = !m.done && m.content.length > 0

    return (
      <div key={i} className="flex gap-3">
        <div className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${
          m.error ? 'bg-rose-50 text-rose-500' : 'bg-warm-100 text-warm-500'
        }`}>
          <Bot size={16} />
        </div>
        <div className="max-w-[80%] min-w-[40%]">
          {hasThinking && (
            <div className="mb-2 rounded-xl border border-warm-200 bg-warm-50 overflow-hidden">
              <button
                onClick={() => toggleThinking(m.id)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-warm-500 hover:text-warm-700 transition-colors"
              >
                {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <Brain size={13} className="text-purple-500" />
                <span>思考过程</span>
                {m.thinkingDone ? (
                  <span className="ml-auto text-[10px] text-sage-500">已完成 ✓</span>
                ) : (
                  <Zap size={10} className="ml-auto text-amber-500 animate-pulse" />
                )}
                <span className="text-[10px] text-warm-500 ml-1">{m.thinking.length} 步</span>
              </button>
              {isExpanded && (
                <div className="border-t border-warm-200/50 px-3 py-2 space-y-0.5 max-h-48 overflow-y-auto">
                  {m.thinking.map((step, j) => (
                    <div key={j} className="text-[11px] text-warm-500 font-mono flex items-start gap-1.5">
                      <span className="text-warm-400 shrink-0 mt-0.5">▸</span>
                      <span>{step}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className={`rounded-2xl rounded-tl-md px-4 py-3 text-sm leading-relaxed ${
            m.error
              ? 'bg-rose-50 border border-rose-200 text-rose-700'
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
                  {m.images.map((img, i) => (
                    <a key={i} href={`/api/files/image?path=${encodeURIComponent(img)}`} target="_blank" rel="noopener" className="block">
                      <img
                        src={`/api/files/image?path=${encodeURIComponent(img)}`}
                        alt={`引用图片 ${i + 1}`}
                        className="w-full h-32 object-cover rounded-xl border border-warm-200 hover:border-coral-300 transition-colors"
                        loading="lazy"
                      />
                    </a>
                  ))}
                </div>
              </div>
            )}
            {m.elapsed && <p className="text-[10px] text-warm-500 mt-1.5 font-mono">{m.elapsed}s</p>}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-4" style={{ height: 'calc(100vh - 7rem)' }}>
      {/* Main chat */}
      <div className="flex-1 flex flex-col card p-0 overflow-hidden">
        <div className="p-4 border-b border-warm-200/60 flex items-center gap-3">
          <h2 className="font-display text-lg font-semibold text-warm-800 flex-1">💬 智能查询</h2>
          <div className="flex gap-1">
            {MODES.map(({ key, icon: Icon, label, desc }) => (
              <button key={key}
                onClick={() => setMode(key)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
                  mode === key
                    ? 'bg-coral-50 text-coral-600 border border-coral-200 shadow-warm-sm'
                    : 'text-warm-500 hover:text-warm-600 hover:bg-warm-50'
                }`}
                title={desc}
              >
                <Icon size={13} /> {label}
              </button>
            ))}
          </div>
        </div>
        <div ref={chatRef} className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full">
              <MessageSquare size={48} className="mb-3 text-warm-200" />
              <p className="text-sm text-warm-500">输入问题开始查询知识库</p>
              <p className="text-xs mt-1 text-warm-400">支持流式输出，实时展示思考过程</p>
            </div>
          )}
          {messages.map((m, i) => renderMessage(m, i))}
          {loading && !messages.some(m => m.role === 'assistant' && !m.done) && (
            <div className="flex gap-3">
              <div className="w-8 h-8 rounded-xl bg-warm-100 flex items-center justify-center">
                <Bot size={16} className="text-warm-500" />
              </div>
              <div className="bg-warm-50 rounded-xl px-4 py-3 flex items-center gap-2 border border-warm-200">
                <div className="flex gap-1">
                  <span className="w-1.5 h-1.5 bg-coral-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 bg-coral-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 bg-coral-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}
        </div>
        <div className="p-4 border-t border-warm-200/60">
          <div className="flex gap-2">
            <input className="input-field flex-1" placeholder="输入你的问题…" value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) send()
                if (e.key === 'Escape') cancelQuery()
              }} />
            {loading ? (
              <button className="btn-danger flex items-center gap-2" onClick={cancelQuery}>
                取消
              </button>
            ) : (
              <button className="btn-primary flex items-center gap-2" onClick={send} disabled={loading}>
                <Send size={16} /> 发送
              </button>
            )}
          </div>
        </div>
      </div>

      {/* History sidebar */}
      <div className="w-64 card p-4 space-y-3 shrink-0 overflow-y-auto">
        <h3 className="flex items-center gap-2 text-sm font-medium text-warm-700">
          <History size={14} /> 查询历史
        </h3>
        {history.map(h => (
          <button key={h.id} onClick={() => loadHistory(h)}
            className="w-full text-left p-2.5 rounded-xl bg-warm-50 hover:bg-warm-100 transition-colors">
            <p className="text-xs text-warm-700 truncate">{h.query}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[10px] text-coral-500 font-mono">{MODES.find(m => m.key === h.mode)?.label || h.mode}</span>
              {h.kb && <span className="text-[10px] text-purple-500/70 font-mono truncate max-w-[80px]" title={h.kb}>{h.kb}</span>}
              <Clock size={10} className="text-warm-500" />
              <span className="text-[10px] text-warm-500">{h.elapsed}s</span>
            </div>
          </button>
        ))}
        {history.length === 0 && (
          <div className="text-center py-8">
            <p className="text-xs text-warm-500">还没有查询记录</p>
            <p className="text-[10px] text-warm-400 mt-1">你的第一个问题正在等待 ✨</p>
          </div>
        )}
      </div>
    </div>
  )
}
