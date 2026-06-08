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

// 暗色主题 Markdown 渲染组件
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

  // SSE 流式查询
  const streamQuery = useCallback(async (query, modeVal) => {
    const kb = getCurrentKB()
    const controller = new AbortController()
    abortRef.current = controller

    const msgId = Date.now().toString()
    // 初始化 AI 消息占位
    setMessages(prev => [...prev, {
      id: msgId,
      role: 'assistant',
      content: '',
      thinking: [],
      thinkingDone: false,
      done: false,
      elapsed: null,
    }])
    setExpandedThinking(prev => ({ ...prev, [msgId]: true }))

    try {
      let headers = { 'Content-Type': 'application/json' }
      try { const t = JSON.parse(localStorage.getItem('raganything_auth') || '{}').token; if (t) headers['Authorization'] = `Bearer ${t}` } catch {}
      const res = await fetch(`/api/query/stream?kb=${kb}`, {
        method: 'POST',
        headers,
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
          try {
            const event = JSON.parse(line.slice(6))
            handleSSEEvent(msgId, event)
          } catch {}
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
        // 完成后自动收起思考过程
        setTimeout(() => {
          setExpandedThinking(prev => ({ ...prev, [msgId]: false }))
        }, 2000)
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
        id: `hist-${item.id}`,
        role: 'assistant',
        content: item.answer,
        thinking: [],
        thinkingDone: true,
        done: true,
        elapsed: item.elapsed,
      },
    ])
    setMode(item.mode)
  }

  const renderMessage = (m, i) => {
    if (m.role === 'user') {
      return (
        <div key={i} className="flex gap-3 flex-row-reverse">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 bg-neon-500/20 text-neon-400">
            <User size={16} />
          </div>
          <div className="max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed bg-neon-500/10 border border-neon-500/20 text-slate-200">
            <div className="whitespace-pre-wrap">{m.content}</div>
          </div>
        </div>
      )
    }

    // AI message
    const hasThinking = m.thinking && m.thinking.length > 0
    const isExpanded = expandedThinking[m.id] !== false
    const showTypingCursor = !m.done && m.content.length > 0

    return (
      <div key={i} className="flex gap-3">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
          m.error ? 'bg-red-500/20 text-red-400' : 'bg-slate-700/50 text-slate-400'
        }`}>
          <Bot size={16} />
        </div>
        <div className="max-w-[80%] min-w-[40%]">
          {/* 思考过程面板 */}
          {hasThinking && (
            <div className="mb-2 rounded-lg border border-slate-700/50 bg-ink-800/50 overflow-hidden">
              <button
                onClick={() => toggleThinking(m.id)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <Brain size={13} className="text-purple-400" />
                <span>思考过程</span>
                {m.thinkingDone ? (
                  <span className="ml-auto text-[10px] text-emerald-400">已完成</span>
                ) : (
                  <Zap size={10} className="ml-auto text-amber-400 animate-pulse" />
                )}
                <span className="text-[10px] text-slate-600 ml-1">{m.thinking.length} 步</span>
              </button>
              {isExpanded && (
                <div className="border-t border-slate-700/30 px-3 py-2 space-y-0.5 max-h-48 overflow-y-auto">
                  {m.thinking.map((step, j) => (
                    <div key={j} className="text-[11px] text-slate-500 font-mono flex items-start gap-1.5">
                      <span className="text-slate-700 shrink-0 mt-0.5">▸</span>
                      <span>{step}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 回答内容 */}
          <div className={`rounded-xl px-4 py-3 text-sm leading-relaxed ${
            m.error
              ? 'bg-red-500/10 border border-red-500/20 text-red-300'
              : 'bg-ink-700 border border-slate-700 text-slate-300'
          }`}>
            <div className="markdown-content">
              <ReactMarkdown components={markdownComponents}>{m.content}</ReactMarkdown>
              {showTypingCursor && <span className="inline-block w-1.5 h-4 bg-neon-400 ml-0.5 animate-pulse align-middle" />}
            </div>
            {/* 引用图片 */}
            {m.images && m.images.length > 0 && (
              <div className="mt-3 pt-3 border-t border-slate-700/50">
                <p className="text-[10px] text-slate-500 mb-2">📷 引用的图片 ({m.images.length})</p>
                <div className="grid grid-cols-2 gap-2">
                  {m.images.map((img, i) => (
                    <a key={i} href={`/api/files/image?path=${encodeURIComponent(img)}`} target="_blank" rel="noopener" className="block">
                      <img
                        src={`/api/files/image?path=${encodeURIComponent(img)}`}
                        alt={`引用图片 ${i + 1}`}
                        className="w-full h-32 object-cover rounded-lg border border-slate-700 hover:border-neon-500/50 transition-colors"
                        loading="lazy"
                      />
                    </a>
                  ))}
                </div>
              </div>
            )}
            {m.elapsed && <p className="text-[10px] text-slate-600 mt-1.5 font-mono">{m.elapsed}s</p>}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-4" style={{ height: 'calc(100vh - 8rem)' }}>
      {/* Main chat */}
      <div className="flex-1 flex flex-col glass p-0 overflow-hidden">
        <div className="p-4 border-b border-slate-700/50 flex items-center gap-3">
          <h2 className="font-display text-lg font-bold text-slate-100 flex-1">智能查询</h2>
          <div className="flex gap-1">
            {MODES.map(({ key, icon: Icon, label, desc }) => (
              <button key={key}
                onClick={() => setMode(key)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  mode === key
                    ? 'bg-neon-500/10 text-neon-400 border border-neon-500/20'
                    : 'text-slate-500 hover:text-slate-300'
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
            <div className="flex flex-col items-center justify-center h-full text-slate-600">
              <MessageSquare size={48} className="mb-3 opacity-30" />
              <p className="text-sm">输入问题开始查询知识库</p>
              <p className="text-xs mt-1 opacity-60">支持流式输出，实时展示思考过程</p>
            </div>
          )}
          {messages.map((m, i) => renderMessage(m, i))}
          {loading && !messages.some(m => m.role === 'assistant' && !m.done) && (
            <div className="flex gap-3">
              <div className="w-8 h-8 rounded-lg bg-slate-700/50 flex items-center justify-center">
                <Bot size={16} className="text-slate-400" />
              </div>
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
        <div className="p-4 border-t border-slate-700/50">
          <div className="flex gap-2">
            <input className="input-field flex-1" placeholder="输入你的问题…" value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) send()
                if (e.key === 'Escape') cancelQuery()
              }} />
            {loading ? (
              <button className="btn-primary flex items-center gap-2 bg-red-500/20 border-red-500/30 text-red-400 hover:bg-red-500/30" onClick={cancelQuery}>
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
      <div className="w-64 glass p-4 space-y-3 shrink-0 overflow-y-auto">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-300">
          <History size={14} /> 查询历史
        </h3>
        {history.map(h => (
          <button key={h.id} onClick={() => loadHistory(h)}
            className="w-full text-left p-2.5 rounded-lg bg-ink-900/30 hover:bg-ink-800/50 transition-colors">
            <p className="text-xs text-slate-300 truncate">{h.query}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[10px] text-neon-400 font-mono">{MODES.find(m => m.key === h.mode)?.label || h.mode}</span>
              {h.kb && <span className="text-[10px] text-purple-400/70 font-mono truncate max-w-[80px]" title={h.kb}>{h.kb}</span>}
              <Clock size={10} className="text-slate-600" />
              <span className="text-[10px] text-slate-600">{h.elapsed}s</span>
            </div>
          </button>
        ))}
        {history.length === 0 && <p className="text-xs text-slate-600">暂无记录</p>}
      </div>
    </div>
  )
}
