import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Send, User, Clock, Plus, Trash2, Edit3, X, ChevronLeft,
  ChevronDown, ChevronRight, Brain, Zap, MessageSquare, ArrowLeft,
  Layers, Cpu, Database, GitGraph, Image, StopCircle, Sparkles,
  BookOpen, Search, AlertTriangle, RefreshCw, Check
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { motion, AnimatePresence } from 'framer-motion'
import { api, getToken } from '../utils/api'
import { useAuth } from '../context/AuthContext'

// ── Mode definitions ───────────────────────────────────────────
const RETRIEVAL_MODES = [
  { key: 'hybrid', icon: Layers, label: '智能混合', desc: '图谱+向量融合检索' },
  { key: 'graph', icon: GitGraph, label: '知识图谱', desc: '基于实体关系检索' },
  { key: 'rrf', icon: Brain, label: '融合排序', desc: 'RRF 多路召回融合' },
  { key: 'local', icon: Zap, label: '精确匹配', desc: '局部上下文精确检索' },
  { key: 'global', icon: Search, label: '全局摘要', desc: '全库摘要式检索' },
  { key: 'naive', icon: MessageSquare, label: '快速问答', desc: '直接向量检索' },
]

const REASONING_MODES = [
  { key: 'none', icon: Zap, label: '直接回答', desc: '不展示推理过程' },
  { key: 'react', icon: Brain, label: 'ReAct 推理', desc: '思考-行动-观察循环' },
  { key: 'cot', icon: Layers, label: '思维链', desc: '逐步推理链' },
]

// ── Markdown render components ──────────────────────────────────
const markdownComponents = {
  h2: ({ children, ...props }) => (
    <h2 className="text-base font-semibold text-ink-primary mt-5 mb-2 pb-1.5 border-b border-cloud-200 dark:border-sky-800/30" {...props}>{children}</h2>
  ),
  h3: ({ children, ...props }) => (
    <h3 className="text-sm font-semibold text-ink-body mt-4 mb-1.5" {...props}>{children}</h3>
  ),
  p: ({ children, ...props }) => (
    <p className="text-sm text-ink-body dark:text-cloud-300 leading-relaxed my-2" {...props}>{children}</p>
  ),
  strong: ({ children, ...props }) => (
    <strong className="font-semibold text-sky-600 dark:text-sky-400" {...props}>{children}</strong>
  ),
  ul: ({ children, ...props }) => (
    <ul className="text-sm text-ink-body dark:text-cloud-300 space-y-1 my-2 pl-4" {...props}>{children}</ul>
  ),
  ol: ({ children, ...props }) => (
    <ol className="text-sm text-ink-body dark:text-cloud-300 space-y-1 my-2 pl-4 list-decimal" {...props}>{children}</ol>
  ),
  li: ({ children, ...props }) => (
    <li className="text-sm text-ink-body dark:text-cloud-300" {...props}>{children}</li>
  ),
  code: ({ inline, className, children, ...props }) => {
    const match = /language-(\w+)/.exec(className || '')
    return !inline ? (
      <div className="my-3 rounded-xl border border-cloud-200 dark:border-sky-800/30 overflow-hidden">
        <div className="bg-cloud-100 dark:bg-sky-900/40 px-3 py-1 text-2xs text-ink-muted dark:text-cloud-500 font-mono">
          {match ? match[1] : 'code'}
        </div>
        <pre className="bg-cloud-50 dark:bg-sky-950/60 p-3 overflow-x-auto text-xs">
          <code className={className} {...props}>{children}</code>
        </pre>
      </div>
    ) : (
      <code className="px-1.5 py-0.5 rounded-md text-xs font-mono bg-cloud-100 dark:bg-sky-900/40 text-amber-700 dark:text-amber-400" {...props}>{children}</code>
    )
  },
  table: ({ children, ...props }) => (
    <div className="my-3 overflow-x-auto">
      <table className="min-w-full text-xs border-collapse" {...props}>{children}</table>
    </div>
  ),
  thead: ({ children, ...props }) => (
    <thead className="bg-cloud-100 dark:bg-sky-900/40" {...props}>{children}</thead>
  ),
  th: ({ children, ...props }) => (
    <th className="border border-cloud-200 dark:border-sky-800/30 px-3 py-1.5 text-left text-ink-body dark:text-cloud-300 font-medium" {...props}>{children}</th>
  ),
  td: ({ children, ...props }) => (
    <td className="border border-cloud-200 dark:border-sky-800/30 px-3 py-1.5 text-ink-muted dark:text-cloud-500" {...props}>{children}</td>
  ),
  blockquote: ({ children, ...props }) => (
    <blockquote className="border border-cloud-200 dark:border-sky-800/30 bg-cloud-50 dark:bg-sky-900/30 rounded-lg px-3 py-1.5 my-2 text-ink-muted dark:text-cloud-500 italic text-xs" {...props}>{children}</blockquote>
  ),
  hr: (props) => <hr className="my-4 border-cloud-200 dark:border-sky-800/30" {...props} />,
  a: ({ children, href, ...props }) => (
    <a href={href} className="text-sky-500 dark:text-sky-400 underline underline-offset-2 hover:text-sky-600 dark:hover:text-sky-300" target="_blank" rel="noopener" {...props}>{children}</a>
  ),
  em: ({ children, ...props }) => (
    <em className="italic text-ink-body dark:text-cloud-300" {...props}>{children}</em>
  ),
}

// ── Welcome suggested questions ─────────────────────────────────
const DEFAULT_SUGGESTIONS = [
  '这个知识库主要包含哪些内容？',
  '帮我总结一下核心概念',
  '最近更新了哪些文档？',
]

// ── Helper: format elapsed ──────────────────────────────────────
function formatElapsed(ms) {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export default function AgentChatPage() {
  const { id: agentId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const chatRef = useRef()
  const abortRef = useRef(null)
  const inputRef = useRef(null)

  // ── User role ───────────────────────────────────────────────
  const userRole = user?.role?.name || 'student'
  const isTeacher = userRole === 'super_admin' || userRole === 'dept_admin' || userRole === 'teacher' || userRole === 'assistant'

  // ── State ────────────────────────────────────────────────────
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
  const [selectedImage, setSelectedImage] = useState(null)
  const [imagePreview, setImagePreview] = useState('')
  const fileInputRef = useRef(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  // ── Blob URL lifecycle tracking ──────────────────────────────
  const blobUrlsRef = useRef(new Set())
  const prevMessagesRef = useRef([])

  const trackBlobUrl = useCallback((url) => {
    if (url && url.startsWith('blob:')) {
      blobUrlsRef.current.add(url)
    }
    return url
  }, [])

  const revokeBlobUrl = useCallback((url) => {
    if (url && blobUrlsRef.current.has(url)) {
      URL.revokeObjectURL(url)
      blobUrlsRef.current.delete(url)
    }
  }, [])

  const cleanupMessageBlobUrls = useCallback((newMessages) => {
    const prevUrls = new Set(
      prevMessagesRef.current
        .filter(m => m.imageUrl && m.imageUrl.startsWith('blob:'))
        .map(m => m.imageUrl)
    )
    const currentUrls = new Set(
      newMessages
        .filter(m => m.imageUrl && m.imageUrl.startsWith('blob:'))
        .map(m => m.imageUrl)
    )
    prevUrls.forEach(url => {
      if (!currentUrls.has(url)) {
        revokeBlobUrl(url)
      }
    })
    prevMessagesRef.current = newMessages
  }, [revokeBlobUrl])

  // Revoke ALL tracked blob URLs on unmount
  useEffect(() => {
    return () => {
      blobUrlsRef.current.forEach(url => {
        try { URL.revokeObjectURL(url) } catch { /* noop */ }
      })
      blobUrlsRef.current.clear()
    }
  }, [])

  // ── Agent loading ────────────────────────────────────────────
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

  // ── Thread management ────────────────────────────────────────
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
      const mapped = t.messages.map((m, i) => ({
        ...m, id: `${threadId}-${i}`, thinking: [], thinkingDone: true, done: true,
      }))
      setMessages(mapped)
      cleanupMessageBlobUrls(mapped)
    } else {
      setMessages([])
      cleanupMessageBlobUrls([])
    }
    api.listConversations(agentId).then(r => {
      const updated = (r.threads || []).find(x => x.id === threadId)
      if (updated?.messages) {
        setThreads(r.threads || [])
        const mapped = updated.messages.map((m, i) => ({
          ...m, id: `${threadId}-${i}`, thinking: [], thinkingDone: true, done: true,
        }))
        setMessages(mapped)
        cleanupMessageBlobUrls(mapped)
      }
    }).catch(e => console.warn('[AgentChat] Failed to load thread messages:', e.message))
  }

  const createThread = async () => {
    const res = await api.createConversation(agentId, '新对话')
    setActiveThreadId(res.thread.id)
    setMessages([])
    cleanupMessageBlobUrls([])
    // Focus input after creating new thread
    setTimeout(() => inputRef.current?.focus(), 100)
  }

  const deleteThread = async (threadId) => {
    await api.deleteConversation(agentId, threadId)
    if (activeThreadId === threadId) { setActiveThreadId(''); setMessages([]); cleanupMessageBlobUrls([]) }
    loadThreads()
  }

  const renameThread = async () => {
    if (!renameTitle.trim()) return
    await api.updateConversation(agentId, renamingThread, renameTitle)
    setRenamingThread(null)
    loadThreads()
  }

  // ── SSE event handler ────────────────────────────────────────
  const handleSSEEvent = (msgId, event) => {
    const { type, content, id: resultId, elapsed, images } = event
    switch (type) {
      case 'thinking':
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
      case 'image_analysis':
        setMessages(prev => prev.map(m => {
          if (m.id !== msgId) return m
          if (event.status === 'done') {
            return { ...m, image_description: event.description_preview || '', similar_count: event.similar_count || 0 }
          }
          return m
        }))
        break
      case 'image_results':
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, similar_images: event.images || [] } : m
        ))
        break
      case 'done':
        setMessages(prev => prev.map(m =>
          m.id === msgId ? {
            ...m, done: true, thinkingDone: true, elapsed,
            images: images || [],
            image_description: event.image_description || m.image_description || null,
            similar_images: event.similar_images || [],
          } : m
        ))
        // Auto-collapse thinking 2s after completion
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

  // ── Stream query ─────────────────────────────────────────────
  const streamQuery = useCallback(async (query, imageFile) => {
    const controller = new AbortController()
    abortRef.current = controller

    const msgId = Date.now().toString()
    setMessages(prev => [...prev, {
      id: msgId, role: 'assistant', content: '',
      thinking: [], thinkingDone: false, done: false, elapsed: null,
      image_description: null, similar_images: [],
    }])
    setExpandedThinking(prev => ({ ...prev, [msgId]: true }))

    try {
      let headers = { 'Content-Type': 'application/json' }
      try { const t = JSON.parse(localStorage.getItem('raganything_auth') || '{}').token; if (t) headers['Authorization'] = `Bearer ${t}` } catch { /* noop */ }
      const body = { query, thread_id: activeThreadId, mode, agent_mode: agentMode }
      if (imageFile) {
        body.image = await new Promise((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(reader.result)
          reader.onerror = reject
          reader.readAsDataURL(imageFile)
        })
      }
      const res = await fetch(`/api/agents/${agentId}/query/stream`, {
        method: 'POST', headers,
        body: JSON.stringify(body),
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
          m.id === msgId ? { ...m, content: m.content || '⏹️ 已取消', done: true, cancelled: true } : m
        ))
      } else {
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, content: `❌ 请求失败: ${e.message}`, done: true, error: true } : m
        ))
      }
      setLoading(false)
      abortRef.current = null
    }
  }, [agentId, activeThreadId, mode, agentMode])

  // ── Send message ─────────────────────────────────────────────
  const send = async () => {
    if ((!input.trim() && !selectedImage) || loading) return
    // Create a thread if none is active
    if (!activeThreadId) {
      const res = await api.createConversation(agentId, '新对话')
      setActiveThreadId(res.thread.id)
      setMessages([])
      cleanupMessageBlobUrls([])
      const q = input.trim()
      const img = selectedImage
      const preview = imagePreview
      setInput('')
      setSelectedImage(null)
      setImagePreview('')
      if (fileInputRef.current) fileInputRef.current.value = ''
      if (preview) trackBlobUrl(preview)
      setMessages(prev => {
        const next = [...prev, { role: 'user', content: q, imageUrl: preview }]
        cleanupMessageBlobUrls(next)
        return next
      })
      setLoading(true)
      await streamQuery(q, img)
      return
    }

    const q = input.trim()
    const img = selectedImage
    const preview = imagePreview
    setInput('')
    setSelectedImage(null)
    setImagePreview('')
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (preview) trackBlobUrl(preview)
    setMessages(prev => {
      const next = [...prev, { role: 'user', content: q, imageUrl: preview }]
      cleanupMessageBlobUrls(next)
      return next
    })
    setLoading(true)
    await streamQuery(q, img)
  }

  const cancelQuery = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setLoading(false)
    }
  }

  // ── Image attachment handlers ─────────────────────────────────
  const ALLOWED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp']

  const handlePickImage = () => fileInputRef.current?.click()

  const handleImageChange = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      alert('不支持的图片格式，仅支持 PNG、JPEG、WebP、GIF、BMP')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      alert('图片大小不能超过 5MB')
      return
    }
    if (imagePreview) revokeBlobUrl(imagePreview)
    const blobUrl = trackBlobUrl(URL.createObjectURL(file))
    setSelectedImage(file)
    setImagePreview(blobUrl)
  }

  const handleRemoveImage = () => {
    revokeBlobUrl(imagePreview)
    setSelectedImage(null)
    setImagePreview('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  // ── Clipboard image paste handler ────────────────────────────
  const handlePaste = (e) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile()
        if (!file) continue
        if (file.size > 5 * 1024 * 1024) {
          alert('图片大小不能超过 5MB')
          return
        }
        e.preventDefault()
        if (imagePreview) revokeBlobUrl(imagePreview)
        const blobUrl = trackBlobUrl(URL.createObjectURL(file))
        setSelectedImage(file)
        setImagePreview(blobUrl)
        return
      }
    }
  }

  // ── Thinking toggle ──────────────────────────────────────────
  const toggleThinking = (msgId) => {
    setExpandedThinking(prev => ({ ...prev, [msgId]: !prev[msgId] }))
  }

  // ── Scroll to bottom on new messages ─────────────────────────
  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  // ── Cleanup on unmount ───────────────────────────────────────
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
      }
    }
  }, [])

  // ── Keyboard: Ctrl+Enter → new thread ────────────────────────
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault()
        createThread()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [agentId])

  // ── Loading state ────────────────────────────────────────────
  if (!agent) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-7rem)]">
        <div className="text-center space-y-4">
          <div className="w-10 h-10 mx-auto rounded-full border-2 border-sky-300 border-t-sky-500 animate-spin" />
          <p className="text-sm text-ink-muted dark:text-cloud-500">正在加载智能体…</p>
        </div>
      </div>
    )
  }

  // ── Suggested questions for empty state ──────────────────────
  const suggestions = (agent.suggested_questions?.length > 0
    ? agent.suggested_questions
    : DEFAULT_SUGGESTIONS
  )

  // ── Get current mode label ───────────────────────────────────
  const currentRetrievalLabel = RETRIEVAL_MODES.find(m => m.key === mode)?.label || '智能混合'
  const currentReasoningLabel = REASONING_MODES.find(m => m.key === agentMode)?.label || '直接回答'

  return (
    <div className="flex gap-3 h-[calc(100vh-7rem)]">
      {/* ═══════════════════════════════════════════════════════════
          SIDEBAR
          ═══════════════════════════════════════════════════════════ */}
      <AnimatePresence>
        {sidebarOpen && (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 220, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.25, 1, 0.5, 1] }}
            className="w-[220px] shrink-0 card p-3 flex flex-col overflow-hidden"
          >
            {/* Back + Agent info */}
            <div className="pb-3 border-b border-cloud-200 dark:border-sky-800/30">
              <button
                onClick={() => navigate('/agents')}
                className="flex items-center gap-1 text-xs text-ink-muted dark:text-cloud-500 hover:text-ink-body dark:hover:text-cloud-300 mb-2.5 transition-colors"
              >
                <ArrowLeft size={12} /> 返回列表
              </button>
              <div className="flex items-center gap-2.5">
                <span className="text-2xl shrink-0">{agent.icon || '🤖'}</span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink-primary dark:text-cloud-200 truncate">{agent.name}</p>
                  <p className="text-2xs text-ink-muted dark:text-cloud-500 truncate">{agent.kb_name}</p>
                </div>
              </div>
            </div>

            {/* Thread list header */}
            <div className="flex items-center justify-between mt-3 mb-1.5">
              <span className="text-2xs font-medium text-ink-muted dark:text-cloud-500 uppercase tracking-wider">对话</span>
              <button
                onClick={createThread}
                className="p-1 rounded-lg text-ink-muted dark:text-cloud-500 hover:text-sky-500 dark:hover:text-sky-400 hover:bg-sky-50 dark:hover:bg-sky-900/30 transition-colors"
                aria-label="新建对话"
                title="新建对话"
              >
                <Plus size={14} />
              </button>
            </div>

            {/* Thread list */}
            <div className="flex-1 space-y-0.5 overflow-y-auto">
              {threads.map(t => (
                <div key={t.id}
                  className={`group flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs cursor-pointer transition-colors ${
                    activeThreadId === t.id
                      ? 'bg-sky-50 dark:bg-sky-900/30 text-sky-600 dark:text-sky-400'
                      : 'text-ink-muted dark:text-cloud-500 hover:text-ink-body dark:hover:text-cloud-300 hover:bg-cloud-100 dark:hover:bg-sky-900/20'
                  }`}
                  role="button"
                  tabIndex={0}
                  aria-label={`对话: ${t.title}`}
                  aria-current={activeThreadId === t.id ? 'true' : undefined}
                  onClick={() => loadThread(t.id)}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); loadThread(t.id) } }}
                >
                  {renamingThread === t.id ? (
                    <input
                      className="input-field flex-1 text-2xs py-0.5 px-1.5"
                      value={renameTitle}
                      onChange={e => setRenameTitle(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') renameThread(); if (e.key === 'Escape') setRenamingThread(null) }}
                      onClick={e => e.stopPropagation()}
                      autoFocus
                    />
                  ) : (
                    <>
                      <span className="flex-1 truncate">{t.title}</span>
                      <button
                        className="opacity-0 group-hover:opacity-100 p-0.5 text-ink-muted dark:text-cloud-500 hover:text-ink-body dark:hover:text-cloud-300 transition-opacity"
                        onClick={e => { e.stopPropagation(); setRenamingThread(t.id); setRenameTitle(t.title) }}
                        aria-label={`重命名 ${t.title}`}
                      >
                        <Edit3 size={10} />
                      </button>
                      <button
                        className="opacity-0 group-hover:opacity-100 p-0.5 text-ink-muted dark:text-cloud-500 hover:text-rose-500 transition-opacity"
                        onClick={e => { e.stopPropagation(); deleteThread(t.id) }}
                        aria-label={`删除 ${t.title}`}
                      >
                        <Trash2 size={10} />
                      </button>
                    </>
                  )}
                </div>
              ))}
              {threads.length === 0 && (
                <div className="text-center py-8">
                  <p className="text-xs text-ink-muted dark:text-cloud-500">暂无对话</p>
                </div>
              )}
            </div>

            {/* Agent info footer */}
            <div className="pt-3 mt-auto border-t border-cloud-200 dark:border-sky-800/30 space-y-1">
              <p className="text-2xs text-ink-muted dark:text-cloud-500 flex items-center gap-1">
                <Database size={10} className="shrink-0" /> {agent.kb_name}
              </p>
              <p className="text-2xs text-ink-muted dark:text-cloud-500 flex items-center gap-1">
                <Cpu size={10} className="shrink-0" /> {agent.llm_model}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ═══════════════════════════════════════════════════════════
          MAIN CHAT
          ═══════════════════════════════════════════════════════════ */}
      <div className="flex-1 flex flex-col card p-0 overflow-hidden min-w-0">
        {/* ── Top bar ─────────────────────────────────────────── */}
        <div className="shrink-0 px-4 py-2.5 border-b border-cloud-200 dark:border-sky-800/30 flex items-center gap-3">
          {/* Sidebar toggle */}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded-lg text-ink-muted dark:text-cloud-500 hover:text-ink-body dark:hover:text-cloud-300 hover:bg-cloud-100 dark:hover:bg-sky-900/30 transition-colors"
            aria-label={sidebarOpen ? '收起侧边栏' : '展开侧边栏'}
          >
            <ChevronLeft size={16} className={`transition-transform duration-200 ${!sidebarOpen ? 'rotate-180' : ''}`} />
          </button>

          {/* Agent identity */}
          <span className="text-xl shrink-0">{agent.icon || '🤖'}</span>
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-ink-primary dark:text-cloud-200 truncate">{agent.name}</h2>
          </div>

          {/* ── Role-aware mode controls ──────────────────────── */}
          {isTeacher ? (
            <div className="flex items-center gap-1.5">
              {/* Retrieval mode dropdown */}
              <div className="relative group">
                <button className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-2xs font-medium text-ink-body dark:text-cloud-300 bg-cloud-50 dark:bg-sky-900/30 border border-cloud-200 dark:border-sky-800/30 hover:border-sky-300 dark:hover:border-sky-700 transition-colors">
                  <Search size={11} className="text-sky-500 dark:text-sky-400" />
                  {currentRetrievalLabel}
                  <ChevronDown size={10} className="text-ink-muted dark:text-cloud-500" />
                </button>
                <div className="absolute right-0 top-full mt-1 w-52 card p-1.5 shadow-cloud-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-150 z-30">
                  {RETRIEVAL_MODES.map(({ key, icon: Icon, label, desc }) => (
                    <button
                      key={key}
                      onClick={() => setMode(key)}
                      className={`w-full flex items-start gap-2 px-2.5 py-2 rounded-lg text-left transition-colors ${
                        mode === key
                          ? 'bg-sky-50 dark:bg-sky-900/40 text-sky-600 dark:text-sky-400'
                          : 'text-ink-body dark:text-cloud-300 hover:bg-cloud-50 dark:hover:bg-sky-900/20'
                      }`}
                    >
                      <Icon size={13} className={`shrink-0 mt-0.5 ${mode === key ? 'text-sky-500' : 'text-ink-muted dark:text-cloud-500'}`} />
                      <div>
                        <p className="text-xs font-medium">{label}</p>
                        <p className="text-2xs text-ink-muted dark:text-cloud-500">{desc}</p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Separator */}
              <div className="w-px h-5 bg-cloud-200 dark:bg-sky-800/30" />

              {/* Reasoning mode dropdown */}
              <div className="relative group">
                <button className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-2xs font-medium text-ink-body dark:text-cloud-300 bg-cloud-50 dark:bg-sky-900/30 border border-cloud-200 dark:border-sky-800/30 hover:border-sky-300 dark:hover:border-sky-700 transition-colors">
                  <Brain size={11} className="text-sage-500" />
                  {currentReasoningLabel}
                  <ChevronDown size={10} className="text-ink-muted dark:text-cloud-500" />
                </button>
                <div className="absolute right-0 top-full mt-1 w-48 card p-1.5 shadow-cloud-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-150 z-30">
                  {REASONING_MODES.map(({ key, icon: Icon, label, desc }) => (
                    <button
                      key={key}
                      onClick={() => setAgentMode(key)}
                      className={`w-full flex items-start gap-2 px-2.5 py-2 rounded-lg text-left transition-colors ${
                        agentMode === key
                          ? 'bg-sky-50 dark:bg-sky-900/40 text-sky-600 dark:text-sky-400'
                          : 'text-ink-body dark:text-cloud-300 hover:bg-cloud-50 dark:hover:bg-sky-900/20'
                      }`}
                    >
                      <Icon size={13} className={`shrink-0 mt-0.5 ${agentMode === key ? 'text-sky-500' : 'text-ink-muted dark:text-cloud-500'}`} />
                      <div>
                        <p className="text-xs font-medium">{label}</p>
                        <p className="text-2xs text-ink-muted dark:text-cloud-500">{desc}</p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            /* Student: subtle mode indicator, no controls */
            <div className="flex items-center gap-1.5">
              <span className="text-2xs text-ink-muted dark:text-cloud-500 flex items-center gap-1">
                <Sparkles size={11} className="text-sky-400" />
                AI 助教
              </span>
            </div>
          )}
        </div>

        {/* ── Messages area ───────────────────────────────────── */}
        <div ref={chatRef} className="flex-1 overflow-y-auto px-4 py-5 space-y-5">
          {/* Empty: no messages */}
          {messages.length === 0 && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center h-full max-w-md mx-auto text-center"
            >
              <span className="text-5xl mb-4">{agent.icon || '🤖'}</span>
              <h3 className="text-lg font-semibold text-ink-primary dark:text-cloud-200 mb-1.5">
                {agent.welcome_message || '你好！有什么可以帮你的？'}
              </h3>
              <p className="text-sm text-ink-muted dark:text-cloud-500 mb-6">
                我是你的 AI 知识助手，可以回答关于知识库的任何问题
              </p>

              {/* Suggested questions */}
              <div className="w-full space-y-2">
                <p className="text-2xs font-medium text-ink-muted dark:text-cloud-500 text-left">💡 试试这些问题</p>
                {suggestions.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      setInput(q)
                      inputRef.current?.focus()
                    }}
                    className="w-full text-left px-4 py-2.5 rounded-xl text-sm text-ink-body dark:text-cloud-300 bg-cloud-50 dark:bg-sky-900/30 border border-cloud-200 dark:border-sky-800/30 hover:border-sky-300 dark:hover:border-sky-700 hover:bg-sky-50 dark:hover:bg-sky-900/40 transition-all group"
                  >
                    <span className="flex items-center gap-2">
                      <span className="text-sky-400 dark:text-sky-500 shrink-0">
                        <MessageSquare size={13} />
                      </span>
                      {q}
                    </span>
                  </button>
                ))}
              </div>

              {/* Keyboard shortcut hint */}
              <p className="text-2xs text-ink-muted dark:text-cloud-500 mt-6">
                按 <kbd className="px-1 py-0.5 rounded text-2xs bg-cloud-100 dark:bg-sky-900/40 border border-cloud-200 dark:border-sky-800/30 font-mono">Enter</kbd> 发送 ·
                按 <kbd className="px-1 py-0.5 rounded text-2xs bg-cloud-100 dark:bg-sky-900/40 border border-cloud-200 dark:border-sky-800/30 font-mono">Shift + Enter</kbd> 换行 ·
                按 <kbd className="px-1 py-0.5 rounded text-2xs bg-cloud-100 dark:bg-sky-900/40 border border-cloud-200 dark:border-sky-800/30 font-mono">Ctrl + Enter</kbd> 新建对话
              </p>
            </motion.div>
          )}

          {/* Messages */}
          <AnimatePresence>
            {messages.map((m, i) => {
              // ── User message ──────────────────────────────────
              if (m.role === 'user') {
                return (
                  <motion.div
                    key={m.id || i}
                    initial={{ opacity: 0, y: 8, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    transition={{ duration: 0.2, ease: [0.25, 1, 0.5, 1] }}
                    className="flex gap-3 flex-row-reverse"
                  >
                    <div className="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 bg-sky-100 dark:bg-sky-900/40 text-sky-500 dark:text-sky-400">
                      <User size={14} />
                    </div>
                    <div className="max-w-[75%] rounded-2xl rounded-tr-md px-4 py-2.5 text-sm bg-sky-50 dark:bg-sky-900/30 border border-sky-100 dark:border-sky-800/30 text-ink-body dark:text-cloud-300">
                      {m.imageUrl && (
                        <img
                          src={m.imageUrl}
                          alt="上传的图片"
                          className="w-full max-w-xs rounded-xl mb-2 border border-sky-100 dark:border-sky-800/30 object-cover"
                        />
                      )}
                      {m.content && <div className="whitespace-pre-wrap break-words">{m.content}</div>}
                    </div>
                  </motion.div>
                )
              }

              // ── AI message ────────────────────────────────────
              const hasThinking = m.thinking?.length > 0
              const isExpanded = !m.thinkingDone || expandedThinking[m.id] !== false
              const showTypingCursor = !m.done && m.content?.length > 0

              return (
                <motion.div
                  key={m.id || i}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, ease: [0.25, 1, 0.5, 1] }}
                  className="flex gap-3"
                >
                  {/* Agent avatar */}
                  <span className="text-xl shrink-0 mt-0.5 select-none">{agent.icon || '🤖'}</span>

                  <div className="max-w-[80%] min-w-[40%] space-y-2">
                    {/* ── Thinking process (Perplexity-like) ───── */}
                    {hasThinking && (
                      <div className="rounded-xl border border-cloud-200 dark:border-sky-800/30 bg-cloud-50/80 dark:bg-sky-900/20 overflow-hidden">
                        <button
                          onClick={() => toggleThinking(m.id)}
                          className="w-full flex items-center gap-2 px-3 py-2 text-xs text-ink-muted dark:text-cloud-500 hover:text-ink-body dark:hover:text-cloud-300 transition-colors"
                        >
                          {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                          <Brain size={12} className="text-sky-500 dark:text-sky-400" />
                          <span className="font-medium text-ink-body dark:text-cloud-300">
                            {m.thinkingDone ? '推理过程' : '正在推理…'}
                          </span>
                          {m.thinkingDone ? (
                            <span className="ml-auto text-2xs text-ink-muted dark:text-cloud-500 flex items-center gap-1">
                              <Check size={10} className="text-sage-500" />
                              {m.thinking.length} 步
                            </span>
                          ) : (
                            <span className="ml-auto flex items-center gap-1 text-2xs text-ink-muted dark:text-cloud-500">
                              <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
                              {m.thinking.length} 步
                            </span>
                          )}
                        </button>

                        {isExpanded && (
                          <div className="border-t border-cloud-200 dark:border-sky-800/30 px-3 py-2.5 space-y-2.5 max-h-80 overflow-y-auto">
                            {m.thinking.map((step, j) => (
                              typeof step === 'object' ? (
                                <div key={j} className="flex gap-2 text-2xs">
                                  {/* Step number */}
                                  <span className="shrink-0 w-5 h-5 rounded-full bg-cloud-100 dark:bg-sky-900/40 flex items-center justify-center text-2xs font-mono text-ink-muted dark:text-cloud-500 mt-0.5">
                                    {j + 1}
                                  </span>
                                  <div className="flex-1 min-w-0 space-y-1">
                                    {/* Thought */}
                                    <div className="flex items-start gap-1.5">
                                      <span className="shrink-0 mt-0.5 text-2xs">💭</span>
                                      <span className="text-ink-body dark:text-cloud-300 leading-relaxed">{step.thought}</span>
                                    </div>
                                    {/* Action */}
                                    {step.action && (
                                      <div className="flex items-start gap-1.5 ml-0.5">
                                        <span className="shrink-0 mt-0.5 text-2xs">🔧</span>
                                        <span className="text-sky-600 dark:text-sky-400 font-medium bg-sky-50 dark:bg-sky-900/30 px-1.5 py-0.5 rounded text-2xs">
                                          {step.action}
                                        </span>
                                      </div>
                                    )}
                                    {/* Observation */}
                                    {step.observation && (
                                      <div className="flex items-start gap-1.5 ml-0.5">
                                        <span className="shrink-0 mt-0.5 text-2xs">📋</span>
                                        <span className="text-sage-600 dark:text-sage-400 whitespace-pre-wrap break-all text-2xs leading-relaxed bg-sage-50 dark:bg-sage-900/20 px-1.5 py-1 rounded">
                                          {step.observation}
                                        </span>
                                      </div>
                                    )}
                                    {/* Elapsed */}
                                    {step.elapsed_ms > 0 && (
                                      <p className="text-2xs text-ink-muted dark:text-cloud-500 font-mono ml-5">
                                        ⏱ {formatElapsed(step.elapsed_ms)}
                                      </p>
                                    )}
                                  </div>
                                </div>
                              ) : (
                                <div key={j} className="text-2xs text-ink-muted dark:text-cloud-500 font-mono flex items-start gap-2">
                                  <span className="shrink-0 w-5 h-5 rounded-full bg-cloud-100 dark:bg-sky-900/40 flex items-center justify-center text-2xs mt-0.5">
                                    {j + 1}
                                  </span>
                                  <span className="leading-relaxed">{step}</span>
                                </div>
                              )
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* ── Answer bubble ────────────────────────── */}
                    <div className={`rounded-2xl rounded-tl-md px-4 py-3 text-sm leading-relaxed ${
                      m.error
                        ? 'bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800/30 text-rose-700 dark:text-rose-300'
                        : m.cancelled
                          ? 'bg-cloud-50 dark:bg-sky-900/20 border border-cloud-200 dark:border-sky-800/30 text-ink-body dark:text-cloud-300'
                          : 'bg-cloud-50 dark:bg-sky-900/20 border border-cloud-200 dark:border-sky-800/30 text-ink-body dark:text-cloud-300'
                    }`}>
                      {/* Error state with retry */}
                      {m.error && (
                        <div className="flex items-center gap-2 mb-2 pb-2 border-b border-rose-200 dark:border-rose-800/30">
                          <AlertTriangle size={13} className="text-rose-500 shrink-0" />
                          <span className="text-xs text-rose-600 dark:text-rose-400 flex-1">回答生成失败</span>
                          <button
                            onClick={() => {
                              // Retry: re-send the last user message
                              const lastUserMsg = [...messages].reverse().find(msg => msg.role === 'user')
                              if (lastUserMsg) {
                                setLoading(true)
                                streamQuery(lastUserMsg.content, null)
                              }
                            }}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-2xs font-medium bg-rose-100 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400 hover:bg-rose-200 dark:hover:bg-rose-900/50 transition-colors"
                          >
                            <RefreshCw size={10} /> 重试
                          </button>
                        </div>
                      )}

                      {/* Cancelled indicator */}
                      {m.cancelled && !m.error && (
                        <div className="flex items-center gap-2 mb-2 text-2xs text-ink-muted dark:text-cloud-500">
                          <StopCircle size={11} />
                          已取消 · 可继续追问或重新提问
                        </div>
                      )}

                      {/* Markdown content */}
                      <div className="markdown-content break-words">
                        <ReactMarkdown components={markdownComponents}>{m.content}</ReactMarkdown>
                        {showTypingCursor && (
                          <span className="inline-block w-1.5 h-4 bg-sky-500 dark:bg-sky-400 ml-0.5 animate-pulse align-middle rounded-sm" />
                        )}
                      </div>

                      {/* ── Source citations ──────────────────── */}
                      {/* Similar images (vision search) */}
                      {m.similar_images && m.similar_images.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-cloud-200 dark:border-sky-800/30">
                          <p className="text-2xs font-medium text-ink-muted dark:text-cloud-500 mb-2 flex items-center gap-1">
                            <Image size={10} /> 视觉相似结果 ({m.similar_images.length})
                          </p>
                          <div className="grid grid-cols-2 gap-2">
                            {m.similar_images.map((sim, si) => (
                              <div key={si} className="bg-white dark:bg-sky-950/60 rounded-lg p-2 border border-cloud-200 dark:border-sky-800/30">
                                {sim.url && (
                                  <img
                                    src={sim.url}
                                    alt={sim.name || ''}
                                    className="w-full h-24 object-cover rounded-md mb-1.5"
                                    loading="lazy"
                                  />
                                )}
                                <p className="text-2xs text-ink-body dark:text-cloud-300 font-medium truncate">
                                  {sim.name || sim.entity_name || sim.image_path?.split('/').pop()}
                                </p>
                                <p className="text-2xs text-sky-500 dark:text-sky-400 font-mono">
                                  相似度 {(sim.score * 100).toFixed(1)}%
                                </p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Referenced images from knowledge base */}
                      {m.images && m.images.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-cloud-200 dark:border-sky-800/30">
                          <p className="text-2xs font-medium text-ink-muted dark:text-cloud-500 mb-2 flex items-center gap-1">
                            <BookOpen size={10} /> 引用来源 ({m.images.length})
                          </p>
                          <div className="grid grid-cols-2 gap-2">
                            {m.images.map((img, idx) => {
                              const token = getToken()
                              const imgUrl = `/api/files/image?path=${encodeURIComponent(img)}${token ? '&token=' + encodeURIComponent(token) : ''}`
                              return (
                                <a key={idx} href={imgUrl} target="_blank" rel="noopener"
                                  className="block rounded-lg overflow-hidden border border-cloud-200 dark:border-sky-800/30 hover:border-sky-300 dark:hover:border-sky-700 transition-colors"
                                >
                                  <img
                                    src={imgUrl}
                                    alt={`引用图片 ${idx + 1}`}
                                    className="w-full h-28 object-cover"
                                    loading="lazy"
                                  />
                                </a>
                              )
                            })}
                          </div>
                        </div>
                      )}

                      {/* Elapsed time */}
                      {m.elapsed && m.done && (
                        <p className="text-2xs text-ink-muted dark:text-cloud-500 mt-2 font-mono">
                          <Clock size={9} className="inline mr-1" />
                          {m.elapsed}s
                        </p>
                      )}

                      {/* Cancelled partial elapsed */}
                      {m.cancelled && !m.done && (
                        <p className="text-2xs text-ink-muted dark:text-cloud-500 mt-2 italic">
                          已取消 · 部分内容已生成
                        </p>
                      )}
                    </div>
                  </div>
                </motion.div>
              )
            })}
          </AnimatePresence>

          {/* Loading: waiting for first token */}
          {loading && !messages.some(m => m.role === 'assistant' && !m.done) && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex gap-3"
            >
              <span className="text-xl select-none">{agent.icon || '🤖'}</span>
              <div className="bg-cloud-50 dark:bg-sky-900/20 rounded-2xl rounded-tl-md px-4 py-3 border border-cloud-200 dark:border-sky-800/30">
                <div className="flex items-center gap-2 text-xs text-ink-muted dark:text-cloud-500">
                  <span className="w-1.5 h-1.5 bg-sky-400 rounded-full animate-pulse" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 bg-sky-400 rounded-full animate-pulse" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 bg-sky-400 rounded-full animate-pulse" style={{ animationDelay: '300ms' }} />
                  <span className="ml-1">正在思考…</span>
                </div>
              </div>
            </motion.div>
          )}
        </div>

        {/* ── Input area ──────────────────────────────────────── */}
        <div className="shrink-0 px-4 py-3 border-t border-cloud-200 dark:border-sky-800/30" onPaste={handlePaste}>
          {/* Image preview */}
          <AnimatePresence>
            {imagePreview && (
              <motion.div
                initial={{ opacity: 0, y: 8, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.95 }}
                className="mb-2.5 inline-block relative"
              >
                <img
                  src={imagePreview}
                  alt="图片预览"
                  className="h-16 rounded-xl border border-cloud-200 dark:border-sky-800/30 object-cover"
                />
                <button
                  onClick={handleRemoveImage}
                  className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-rose-100 dark:bg-rose-900/40 hover:bg-rose-200 dark:hover:bg-rose-900/60 text-rose-500 rounded-full flex items-center justify-center transition-colors"
                  aria-label="移除图片"
                >
                  <X size={10} />
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          <div className="flex gap-2 items-end">
            {/* Hidden file input */}
            <input
              type="file" accept="image/*" ref={fileInputRef}
              onChange={handleImageChange} className="hidden"
            />

            {/* Image upload button */}
            <button
              className="p-2 rounded-xl text-ink-muted dark:text-cloud-500 hover:text-sky-500 dark:hover:text-sky-400 hover:bg-sky-50 dark:hover:bg-sky-900/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
              onClick={handlePickImage}
              title="上传图片搜索"
              aria-label="上传图片"
              disabled={loading}
            >
              <Image size={18} />
            </button>

            {/* Text input */}
            <div className="flex-1 relative">
              <textarea
                ref={inputRef}
                className="input-field w-full resize-none text-sm py-2.5 max-h-32"
                placeholder={`向 ${agent.name} 提问…`}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send()
                  }
                  if (e.key === 'Escape') {
                    if (loading) cancelQuery()
                    else setInput('')
                  }
                }}
                rows={1}
                disabled={loading && !abortRef.current}
                style={{ minHeight: '42px' }}
                onInput={e => {
                  // Auto-resize
                  const el = e.target
                  el.style.height = 'auto'
                  el.style.height = Math.min(el.scrollHeight, 128) + 'px'
                }}
              />
            </div>

            {/* Send / Cancel button */}
            {loading ? (
              <button
                className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-medium bg-rose-50 dark:bg-rose-900/20 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800/30 hover:bg-rose-100 dark:hover:bg-rose-900/30 transition-colors shrink-0"
                onClick={cancelQuery}
              >
                <StopCircle size={14} />
                取消
              </button>
            ) : (
              <button
                className="btn-primary flex items-center gap-1.5 px-4 py-2.5 text-sm shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
                onClick={send}
                disabled={!input.trim() && !selectedImage}
              >
                <Send size={14} />
                发送
              </button>
            )}
          </div>

          {/* Mode indicator (subtle, always visible) */}
          <div className="flex items-center justify-between mt-2">
            <div className="flex items-center gap-3">
              {isTeacher && (
                <>
                  <span className="text-2xs text-ink-muted dark:text-cloud-500 flex items-center gap-1">
                    <Search size={10} />
                    {currentRetrievalLabel}
                  </span>
                  <span className="text-2xs text-ink-muted dark:text-cloud-500 flex items-center gap-1">
                    <Brain size={10} />
                    {currentReasoningLabel}
                  </span>
                </>
              )}
              {!isTeacher && (
                <span className="text-2xs text-ink-muted dark:text-cloud-500 flex items-center gap-1">
                  <Sparkles size={10} />
                  AI 助教模式
                </span>
              )}
            </div>
            <span className="text-2xs text-ink-muted dark:text-cloud-500">
              {agent.kb_name} · {agent.llm_model}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
