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

// ── 模式定义 ───────────────────────────────────────────
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

// ── Markdown 渲染组件 ──────────────────────────────────
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

// ── 欢迎页建议问题 ─────────────────────────────────
const DEFAULT_SUGGESTIONS = [
  '这个知识库主要包含哪些内容？',
  '帮我总结一下核心概念',
  '最近更新了哪些文档？',
]

// ── 工具函数：格式化耗时 ──────────────────────────────────────
function formatElapsed(ms) {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function mapThreadMessages(threadId, messages = []) {
  return messages.map((message, index) => ({
    ...message,
    id: `${threadId}-${index}`,
    thinking: [],
    thinkingDone: true,
    done: true,
  }))
}

async function readStreamErrorMessage(res) {
  const fallback = res.statusText || `HTTP ${res.status}`
  const text = await res.text().catch(() => '')
  if (!text.trim()) return fallback
  try {
    const parsed = JSON.parse(text)
    if (typeof parsed?.detail === 'string') return parsed.detail
  } catch {
    return text
  }
  return fallback
}

export default function AgentChatPage({ onToast }) {
  const { id: agentId } = useParams()
  const navigate = useNavigate()
  const { hasPermission } = useAuth()
  const chatRef = useRef()
  const abortRef = useRef(null)
  const inputRef = useRef(null)
  const activeThreadIdRef = useRef('')

  // ── 状态 ────────────────────────────────────────────────────
  const [agent, setAgent] = useState(null)
  const [threads, setThreads] = useState([])
  const [activeThreadId, setActiveThreadId] = useState('')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [modeOverride, setModeOverride] = useState(null)
  const [agentModeOverride, setAgentModeOverride] = useState(null)
  const [loading, setLoading] = useState(false)
  const [expandedThinking, setExpandedThinking] = useState({})
  const [renamingThread, setRenamingThread] = useState(null)
  const [renameTitle, setRenameTitle] = useState('')
  const [selectedImage, setSelectedImage] = useState(null)
  const [imagePreview, setImagePreview] = useState('')
  const fileInputRef = useRef(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  // ── 消息编辑状态 ────────────────────────────────────
  const [editingMsgId, setEditingMsgId] = useState(null)  // msg.msg_id currently being edited
  const [editContent, setEditContent] = useState('')       // textarea content

  // ── Blob URL 生命周期追踪 ──────────────────────────────
  const blobUrlsRef = useRef(new Set())
  const prevMessagesRef = useRef([])
  const canAdjustModes = hasPermission('agent:read')
  const effectiveMode = modeOverride ?? agent?.query_mode ?? 'hybrid'
  const effectiveAgentMode = agentModeOverride ?? agent?.agent_mode ?? 'none'

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

    // 卸载时释放所有已追踪的 Blob URL
  useEffect(() => {
    return () => {
      blobUrlsRef.current.forEach(url => {
        try { URL.revokeObjectURL(url) } catch { /* 无需处理 */ }
      })
      blobUrlsRef.current.clear()
    }
  }, [])

  useEffect(() => {
    activeThreadIdRef.current = activeThreadId
  }, [activeThreadId])

  const loadAgent = useCallback(async ({ silent = false } = {}) => {
    try {
      const response = await api.listAgents()
      const nextAgent = (response.agents || []).find(item => item.id === agentId)
      if (!nextAgent) {
        if (!silent) {
          onToast?.('未找到该智能体，或当前账号已无访问权限。', 'error')
          navigate('/agents')
        }
        return null
      }
      setAgent(nextAgent)
      return nextAgent
    } catch (e) {
      if (!silent) {
        onToast?.(e.message || '加载智能体失败', 'error')
      }
      console.warn('[AgentChat] Failed to load agent:', e.message)
      return null
    }
  }, [agentId, navigate, onToast])

  // ── 智能体加载 ────────────────────────────────────────────
  useEffect(() => {
    setModeOverride(null)
    setAgentModeOverride(null)
    loadAgent()
    loadThreads(true)
  }, [agentId, loadAgent])

  useEffect(() => {
    const handleFocus = () => {
      loadAgent({ silent: true })
    }
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        loadAgent({ silent: true })
      }
    }
    window.addEventListener('focus', handleFocus)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      window.removeEventListener('focus', handleFocus)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [loadAgent])

  // ── 会话线程管理 ────────────────────────────────────────
  const loadThreads = async (autoSelect = false) => {
    try {
      const response = await api.listConversations(agentId)
      const nextThreads = response.threads || []
      setThreads(nextThreads)
      if (nextThreads.length > 0 && autoSelect) {
        await loadThread(nextThreads[0].id)
      }
    } catch (e) {
      console.warn('[AgentChat] Failed to load conversations:', e.message)
    }
  }

  const loadThread = async (threadId) => {
    if (abortRef.current && activeThreadIdRef.current && activeThreadIdRef.current !== threadId) {
      abortRef.current.abort()
    }
    activeThreadIdRef.current = threadId
    setActiveThreadId(threadId)
    setMessages([])
    cleanupMessageBlobUrls([])
    // 获取带消息的会话线程（包含 msg_id，用于支持编辑）
    try {
      const response = await api.getConversation(agentId, threadId)
      const thread = response.thread
      if (thread?.messages) {
        const mapped = mapThreadMessages(threadId, thread.messages)
        setMessages(mapped)
        cleanupMessageBlobUrls(mapped)
      }
      // 同步刷新会话线程列表
      loadThreads()
    } catch (e) {
      console.warn('[AgentChat] Failed to load thread:', e.message)
      onToast?.(e.message || '加载会话失败', 'error')
    }
  }

  const createThread = async () => {
    try {
      const res = await api.createConversation(agentId, '新对话')
      activeThreadIdRef.current = res.thread.id
      setActiveThreadId(res.thread.id)
      setMessages([])
      cleanupMessageBlobUrls([])
      loadThreads()
      // 新建会话线程后聚焦输入框
      setTimeout(() => inputRef.current?.focus(), 100)
      return res.thread.id
    } catch (e) {
      onToast?.(e.message || '创建会话失败', 'error')
      throw e
    }
  }

  const deleteThread = async (threadId) => {
    try {
      if (activeThreadIdRef.current === threadId && abortRef.current) {
        abortRef.current.abort()
      }
      await api.deleteConversation(agentId, threadId)
      if (activeThreadIdRef.current === threadId) {
        activeThreadIdRef.current = ''
        setActiveThreadId('')
        setMessages([])
        cleanupMessageBlobUrls([])
      }
      loadThreads()
      onToast?.('会话已删除', 'success')
    } catch (e) {
      onToast?.(e.message || '删除会话失败', 'error')
    }
  }

  const renameThread = async () => {
    if (!renameTitle.trim()) return
    try {
      await api.updateConversation(agentId, renamingThread, renameTitle)
      setRenamingThread(null)
      loadThreads()
      onToast?.('会话名称已更新', 'success')
    } catch (e) {
      onToast?.(e.message || '重命名会话失败', 'error')
    }
  }

  // ── 消息编辑处理 ──────────────────────────────────
  const startEdit = (msg) => {
    setEditingMsgId(msg.msg_id)
    setEditContent(msg.content)
  }

  const cancelEdit = () => {
    setEditingMsgId(null)
    setEditContent('')
  }

  const saveEdit = async (msg) => {
    if (!editContent.trim() || editContent.trim() === (msg.content || '').trim()) {
      setEditingMsgId(null)
      setEditContent('')
      return
    }
    try {
      await api.updateMessage(agentId, activeThreadId, msg.msg_id, editContent.trim())
      setMessages(prev => prev.map(m =>
        m.msg_id === msg.msg_id ? { ...m, content: editContent.trim(), edited: true } : m
      ))
      setEditingMsgId(null)
      setEditContent('')
      onToast?.('消息已更新', 'success')
    } catch (e) {
      onToast?.(e.message || '保存消息失败', 'error')
    }
  }

  // ── SSE 事件处理 ────────────────────────────────────────
  const handleSSEEvent = (msgId, event, threadId) => {
    const { type, content, elapsed, images } = event
    const isVisibleThread = !threadId || activeThreadIdRef.current === threadId
    switch (type) {
      case 'thinking':
        if (!isVisibleThread) break
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
        if (!isVisibleThread) break
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, content: m.content + content } : m
        ))
        break
      case 'image_analysis':
        if (!isVisibleThread) break
        setMessages(prev => prev.map(m => {
          if (m.id !== msgId) return m
          if (event.status === 'done') {
            return { ...m, image_description: event.description_preview || '', similar_count: event.similar_count || 0 }
          }
          return m
        }))
        break
      case 'image_results':
        if (!isVisibleThread) break
        setMessages(prev => prev.map(m =>
          m.id === msgId ? { ...m, similar_images: event.images || [] } : m
        ))
        break
      case 'done':
        if (isVisibleThread) {
          setMessages(prev => prev.map(m =>
            m.id === msgId ? {
              ...m, done: true, thinkingDone: true, elapsed,
              images: images || [],
              image_description: event.image_description || m.image_description || null,
              similar_images: event.similar_images || [],
            } : m
          ))
          // 完成 2 秒后自动折叠思考过程
          setTimeout(() => setExpandedThinking(prev => ({ ...prev, [msgId]: false })), 2000)
        }
        setLoading(false)
        abortRef.current = null
        loadThreads()
        // 重新加载会话消息，从后端获取真实 msg_id 以支持编辑
        if (threadId && activeThreadIdRef.current === threadId) {
          api.getConversation(agentId, threadId).then(r => {
            if (r.thread?.messages) {
              const mapped = mapThreadMessages(threadId, r.thread.messages)
              setMessages(mapped)
              cleanupMessageBlobUrls(mapped)
            }
          }).catch(() => {})
        }
        break
      case 'error':
        if (isVisibleThread) {
          setMessages(prev => prev.map(m =>
            m.id === msgId ? { ...m, content: content, done: true, error: true } : m
          ))
        }
        setLoading(false)
        abortRef.current = null
        break
      case 'agent_info': break
    }
  }

  // ── 流式查询 ─────────────────────────────────────────────
  const streamQuery = useCallback(async (query, imageFile, threadId) => {
    const controller = new AbortController()
    abortRef.current = controller
    activeThreadIdRef.current = threadId

    const msgId = Date.now().toString()
    if (activeThreadIdRef.current === threadId) {
      setMessages(prev => [...prev, {
        id: msgId, role: 'assistant', content: '',
        thinking: [], thinkingDone: false, done: false, elapsed: null,
        image_description: null, similar_images: [],
      }])
    }
    setExpandedThinking(prev => ({ ...prev, [msgId]: true }))

    try {
      let headers = { 'Content-Type': 'application/json' }
      const token = getToken()
      if (token) {
        headers['Authorization'] = `Bearer ${token}`
      }
      const body = { query, thread_id: threadId }
      if (modeOverride !== null) {
        body.mode = effectiveMode
      }
      if (agentModeOverride !== null) {
        body.agent_mode = effectiveAgentMode
      }
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

      if (!res.ok || !res.body) {
        throw new Error(await readStreamErrorMessage(res))
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
          try { handleSSEEvent(msgId, JSON.parse(line.slice(6)), threadId) } catch (parseErr) {
            console.warn('[AgentChat] SSE parse error:', parseErr.message, 'line:', line.slice(0, 100))
          }
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        if (activeThreadIdRef.current === threadId) {
          setMessages(prev => prev.map(m =>
            m.id === msgId ? { ...m, content: m.content || '已取消', done: true, cancelled: true } : m
          ))
        }
      } else {
        if (activeThreadIdRef.current === threadId) {
          setMessages(prev => prev.map(m =>
            m.id === msgId ? { ...m, content: `请求失败: ${e.message}`, done: true, error: true } : m
          ))
        }
        onToast?.(e.message || '发送请求失败', 'error')
      }
      setLoading(false)
      abortRef.current = null
    }
  }, [agentId, agentModeOverride, effectiveAgentMode, effectiveMode, modeOverride, onToast])

  // ── 发送消息 ─────────────────────────────────────────────
  const send = async () => {
    if ((!input.trim() && !selectedImage) || loading) return
    // 如果没有活动会话线程，则先创建一个
    if (!activeThreadId) {
      const newThreadId = await createThread()
      if (!newThreadId) return
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
      await streamQuery(q, img, newThreadId)
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
    await streamQuery(q, img, activeThreadId)
  }

  const cancelQuery = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setLoading(false)
    }
  }

  // ── 图片附件处理 ─────────────────────────────────
  const ALLOWED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp']

  const handlePickImage = () => fileInputRef.current?.click()

  const handleImageChange = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      e.target.value = ''
      onToast?.('不支持的图片格式，仅支持 PNG、JPEG、WebP、GIF、BMP', 'error')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      e.target.value = ''
      onToast?.('图片大小不能超过 5MB', 'error')
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

  // ── 剪贴板图片粘贴处理 ────────────────────────────
  const handlePaste = (e) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile()
        if (!file) continue
        if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
          onToast?.('不支持的图片格式，仅支持 PNG、JPEG、WebP、GIF、BMP', 'error')
          return
        }
        if (file.size > 5 * 1024 * 1024) {
          onToast?.('图片大小不能超过 5MB', 'error')
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

  // ── 思考过程开关 ──────────────────────────────────────────
  const toggleThinking = (msgId) => {
    setExpandedThinking(prev => ({ ...prev, [msgId]: !prev[msgId] }))
  }

  // ── 新消息出现时滚动到底部 ─────────────────────────
  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  // ── 卸载时清理 ───────────────────────────────────────
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
      }
    }
  }, [])

  // ── 键盘：Ctrl+Enter 新建会话 ────────────────────────
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

  // ── 加载状态 ────────────────────────────────────────────
  if (!agent) {
    return (
      <div className="agent-chat-page flex items-center justify-center min-h-0 w-full">
        <div className="text-center space-y-4">
          <div className="w-10 h-10 mx-auto rounded-full border-2 border-sky-300 border-t-sky-500 animate-spin" />
          <p className="text-sm text-ink-muted dark:text-cloud-500">正在加载智能体…</p>
        </div>
      </div>
    )
  }

  // ── 空状态建议问题 ──────────────────────
  const suggestions = (agent.suggested_questions?.length > 0
    ? agent.suggested_questions
    : DEFAULT_SUGGESTIONS
  )

  // ── 获取当前模式标签 ───────────────────────────────────
  const currentRetrievalLabel = RETRIEVAL_MODES.find(m => m.key === effectiveMode)?.label || '智能混合'
  const currentReasoningLabel = REASONING_MODES.find(m => m.key === effectiveAgentMode)?.label || '直接回答'

  return (
    <div className="agent-chat-page flex gap-3 min-h-0 w-full">
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
            className="agent-chat-sidebar w-[220px] shrink-0 card p-3 flex flex-col overflow-hidden"
          >
            {/* 返回与智能体信息 */}
            <div className="pb-3 border-b border-cloud-200 dark:border-sky-800/30">
              <button
                onClick={() => navigate('/agents')}
                className="flex items-center gap-1 text-xs text-ink-muted dark:text-cloud-500 hover:text-ink-body dark:hover:text-cloud-300 mb-2.5 transition-colors"
              >
                <ArrowLeft size={12} /> 返回列表
              </button>
              <div className="flex items-center gap-2.5">
                <span className="text-2xl shrink-0">{agent.icon}</span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink-primary dark:text-cloud-200 truncate">{agent.name}</p>
                  <p className="text-2xs text-ink-muted dark:text-cloud-500 truncate">{agent.kb_name}</p>
                </div>
              </div>
            </div>

            {/* 会话线程列表头部 */}
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

            {/* 会话线程列表 */}
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

            {/* 智能体信息底部 */}
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
      <div className="agent-chat-main flex-1 flex flex-col card p-0 overflow-hidden min-w-0">
        {/* ── 顶部栏 ─────────────────────────────────────────── */}
        <div className="shrink-0 px-4 py-2.5 border-b border-cloud-200 dark:border-sky-800/30 flex items-center gap-3">
          {/* 侧边栏开关 */}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded-lg text-ink-muted dark:text-cloud-500 hover:text-ink-body dark:hover:text-cloud-300 hover:bg-cloud-100 dark:hover:bg-sky-900/30 transition-colors"
            aria-label={sidebarOpen ? '收起侧边栏' : '展开侧边栏'}
          >
            <ChevronLeft size={16} className={`transition-transform duration-200 ${!sidebarOpen ? 'rotate-180' : ''}`} />
          </button>

          {/* 智能体身份信息 */}
          <span className="text-xl shrink-0">{agent.icon}</span>
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-ink-primary dark:text-cloud-200 truncate">{agent.name}</h2>
          </div>

          {/* ── 按角色显示的模式控制 ──────────────────────── */}
          {canAdjustModes ? (
            <div className="flex items-center gap-1.5">
              {/* 检索模式下拉框 */}
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
                      onClick={() => setModeOverride(key)}
                      className={`w-full flex items-start gap-2 px-2.5 py-2 rounded-lg text-left transition-colors ${
                        effectiveMode === key
                          ? 'bg-sky-50 dark:bg-sky-900/40 text-sky-600 dark:text-sky-400'
                          : 'text-ink-body dark:text-cloud-300 hover:bg-cloud-50 dark:hover:bg-sky-900/20'
                      }`}
                    >
                      <Icon size={13} className={`shrink-0 mt-0.5 ${effectiveMode === key ? 'text-sky-500' : 'text-ink-muted dark:text-cloud-500'}`} />
                      <div>
                        <p className="text-xs font-medium">{label}</p>
                        <p className="text-2xs text-ink-muted dark:text-cloud-500">{desc}</p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* 分隔线 */}
              <div className="w-px h-5 bg-cloud-200 dark:bg-sky-800/30" />

              {/* 推理模式下拉框 */}
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
                      onClick={() => setAgentModeOverride(key)}
                      className={`w-full flex items-start gap-2 px-2.5 py-2 rounded-lg text-left transition-colors ${
                        effectiveAgentMode === key
                          ? 'bg-sky-50 dark:bg-sky-900/40 text-sky-600 dark:text-sky-400'
                          : 'text-ink-body dark:text-cloud-300 hover:bg-cloud-50 dark:hover:bg-sky-900/20'
                      }`}
                    >
                      <Icon size={13} className={`shrink-0 mt-0.5 ${effectiveAgentMode === key ? 'text-sky-500' : 'text-ink-muted dark:text-cloud-500'}`} />
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
            /* 学生端：仅显示弱提示，不显示控制项 */
            <div className="flex items-center gap-1.5">
              <span className="text-2xs text-ink-muted dark:text-cloud-500 flex items-center gap-1">
                <Sparkles size={11} className="text-sky-400" />
                AI 助教
              </span>
            </div>
          )}
        </div>

        {/* ── 消息区域 ───────────────────────────────────── */}
        <div ref={chatRef} className="agent-chat-messages flex-1 overflow-y-auto px-4 py-5 space-y-5">
          {/* 空状态：暂无消息 */}
          {messages.length === 0 && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center h-full max-w-md mx-auto text-center"
            >
              <span className="text-5xl mb-4">{agent.icon}</span>
              <h3 className="text-lg font-semibold text-ink-primary dark:text-cloud-200 mb-1.5">
                {agent.welcome_message || '你好！有什么可以帮你的？'}
              </h3>
              <p className="text-sm text-ink-muted dark:text-cloud-500 mb-6">
                我是你的 AI 知识助手，可以回答关于知识库的任何问题
              </p>

              {/* 建议问题 */}
              <div className="w-full space-y-2">
                <p className="text-2xs font-medium text-ink-muted dark:text-cloud-500 text-left">试试这些问题</p>
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

              {/* 键盘快捷键提示 */}
              <p className="text-2xs text-ink-muted dark:text-cloud-500 mt-6">
                按 <kbd className="px-1 py-0.5 rounded text-2xs bg-cloud-100 dark:bg-sky-900/40 border border-cloud-200 dark:border-sky-800/30 font-mono">Enter</kbd> 发送 ·
                按 <kbd className="px-1 py-0.5 rounded text-2xs bg-cloud-100 dark:bg-sky-900/40 border border-cloud-200 dark:border-sky-800/30 font-mono">Shift + Enter</kbd> 换行 ·
                按 <kbd className="px-1 py-0.5 rounded text-2xs bg-cloud-100 dark:bg-sky-900/40 border border-cloud-200 dark:border-sky-800/30 font-mono">Ctrl + Enter</kbd> 新建对话
              </p>
            </motion.div>
          )}

          {/* 消息列表 */}
          <AnimatePresence>
            {messages.map((m, i) => {
              // ── 用户消息 ──────────────────────────────────
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

              // ── AI 消息 ────────────────────────────────────
              const hasThinking = m.thinking?.length > 0
              const isExpanded = !m.thinkingDone || expandedThinking[m.id] !== false
              const showTypingCursor = !m.done && m.content?.length > 0

              return (
                <motion.div
                  key={m.id || i}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, ease: [0.25, 1, 0.5, 1] }}
                  className="flex gap-3 group"
                >
                  {/* 智能体头像 */}
                  <span className="text-xl shrink-0 mt-0.5 select-none">{agent.icon}</span>

                  <div className="max-w-[80%] min-w-[40%] space-y-2">
                    {/* ── 思考过程（类 Perplexity 样式）───── */}
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
                              {/* 步骤编号 */}
                                  <span className="shrink-0 w-5 h-5 rounded-full bg-cloud-100 dark:bg-sky-900/40 flex items-center justify-center text-2xs font-mono text-ink-muted dark:text-cloud-500 mt-0.5">
                                    {j + 1}
                                  </span>
                                  <div className="flex-1 min-w-0 space-y-1">
                              {/* 思考 */}
                                    <div className="flex items-start gap-1.5">
                                      <span className="shrink-0 mt-0.5 text-2xs text-ink-muted">思考</span>
                                      <span className="text-ink-body dark:text-cloud-300 leading-relaxed">{step.thought}</span>
                                    </div>
                              {/* 动作 */}
                                    {step.action && (
                                      <div className="flex items-start gap-1.5 ml-0.5">
                                        <span className="shrink-0 mt-0.5 text-2xs text-ink-muted">工具</span>
                                        <span className="text-sky-600 dark:text-sky-400 font-medium bg-sky-50 dark:bg-sky-900/30 px-1.5 py-0.5 rounded text-2xs">
                                          {step.action}
                                        </span>
                                      </div>
                                    )}
                              {/* 观察结果 */}
                                    {step.observation && (
                                      <div className="flex items-start gap-1.5 ml-0.5">
                                        <span className="shrink-0 mt-0.5 text-2xs text-ink-muted">结果</span>
                                        <span className="text-sage-600 dark:text-sage-400 whitespace-pre-wrap break-all text-2xs leading-relaxed bg-sage-50 dark:bg-sage-900/20 px-1.5 py-1 rounded">
                                          {step.observation}
                                        </span>
                                      </div>
                                    )}
                              {/* 耗时 */}
                                    {step.elapsed_ms > 0 && (
                                      <p className="text-2xs text-ink-muted dark:text-cloud-500 font-mono ml-5">
                                        {formatElapsed(step.elapsed_ms)}
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

                    {/* ── 回答气泡 ────────────────────────── */}
                    <div className={`relative rounded-2xl rounded-tl-md px-4 py-3 text-sm leading-relaxed ${
                      m.error
                        ? 'bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800/30 text-rose-700 dark:text-rose-300'
                        : m.cancelled
                          ? 'bg-cloud-50 dark:bg-sky-900/20 border border-cloud-200 dark:border-sky-800/30 text-ink-body dark:text-cloud-300'
                          : 'bg-cloud-50 dark:bg-sky-900/20 border border-cloud-200 dark:border-sky-800/30 text-ink-body dark:text-cloud-300'
                    }`}>
                      {/* 带重试入口的错误状态 */}
                      {m.error && (
                        <div className="flex items-center gap-2 mb-2 pb-2 border-b border-rose-200 dark:border-rose-800/30">
                          <AlertTriangle size={13} className="text-rose-500 shrink-0" />
                          <span className="text-xs text-rose-600 dark:text-rose-400 flex-1">回答生成失败</span>
                          <button
                            onClick={() => {
                              // 重试：重新发送上一条用户消息
                              const lastUserMsg = [...messages].reverse().find(msg => msg.role === 'user')
                              if (lastUserMsg) {
                                setLoading(true)
                                streamQuery(lastUserMsg.content, null, activeThreadIdRef.current)
                              }
                            }}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-2xs font-medium bg-rose-100 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400 hover:bg-rose-200 dark:hover:bg-rose-900/50 transition-colors"
                          >
                            <RefreshCw size={10} /> 重试
                          </button>
                        </div>
                      )}

                      {/* 已取消提示 */}
                      {m.cancelled && !m.error && (
                        <div className="flex items-center gap-2 mb-2 text-2xs text-ink-muted dark:text-cloud-500">
                          <StopCircle size={11} />
                          已取消 · 可继续追问或重新提问
                        </div>
                      )}

                      {/* ── 编辑模式或展示模式 ─────────── */}
                      {editingMsgId === m.msg_id ? (
                        <div className="space-y-2">
                          <textarea
                            className="input-field w-full text-sm font-mono resize-y min-h-[120px]"
                            value={editContent}
                            onChange={e => setEditContent(e.target.value)}
                            onKeyDown={e => {
                              if (e.key === 'Escape') cancelEdit()
                              if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') saveEdit(m)
                            }}
                            autoFocus
                          />
                          <div className="flex items-center justify-between">
                            <span className="text-2xs text-ink-muted dark:text-cloud-500">
                              {editContent.length}/10000 · Markdown · Ctrl+Enter 保存 · Esc 取消
                            </span>
                            <div className="flex gap-2">
                              <button
                                className="btn-ghost text-xs py-1 px-3"
                                onClick={cancelEdit}
                              >
                                取消
                              </button>
                              <button
                                className="btn-primary text-xs py-1 px-3 disabled:opacity-40"
                                onClick={() => saveEdit(m)}
                                disabled={!editContent.trim() || editContent.trim() === (m.content || '').trim()}
                              >
                                保存
                              </button>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <>
                          {/* 编辑按钮：悬停显示，仅用于带有效数据库 ID 的已完成助手消息 */}
                          {m.done && !m.error && !m.cancelled && m.msg_id != null && (
                            <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                className="p-1 rounded-lg text-ink-muted dark:text-cloud-500 hover:text-sky-500 dark:hover:text-sky-400 hover:bg-sky-50 dark:hover:bg-sky-900/30 transition-colors"
                                onClick={() => startEdit(m)}
                                title="编辑回答"
                                aria-label="编辑回答"
                              >
                                <Edit3 size={13} />
                              </button>
                            </div>
                          )}

                          {/* Markdown 内容 */}
                          <div className="markdown-content break-words">
                            <ReactMarkdown components={markdownComponents}>{m.content}</ReactMarkdown>
                            {showTypingCursor && (
                              <span className="inline-block w-1.5 h-4 bg-sky-500 dark:bg-sky-400 ml-0.5 animate-pulse align-middle rounded-sm" />
                            )}
                          </div>

                          {/* 已编辑提示 */}
                          {m.edited && (
                            <p className="text-2xs text-ink-muted dark:text-cloud-500 mt-2 italic">(已编辑)</p>
                          )}
                        </>
                      )}

                      {/* ── 来源引用 ──────────────────── */}
                      {/* 相似图片（视觉检索） */}
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

                      {/* 知识库引用图片 */}
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

                      {/* 耗时 */}
                      {m.elapsed && m.done && (
                        <p className="text-2xs text-ink-muted dark:text-cloud-500 mt-2 font-mono">
                          <Clock size={9} className="inline mr-1" />
                          {m.elapsed}s
                        </p>
                      )}

                      {/* 取消前的部分耗时 */}
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

          {/* 加载中：等待首个令牌 */}
          {loading && !messages.some(m => m.role === 'assistant' && !m.done) && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex gap-3"
            >
              <span className="text-xl select-none">{agent.icon}</span>
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

        {/* ── 输入区域 ──────────────────────────────────────── */}
        <div className="agent-chat-composer shrink-0 px-4 py-3 border-t border-cloud-200 dark:border-sky-800/30" onPaste={handlePaste}>
          {/* 图片预览 */}
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
            {/* 隐藏文件输入 */}
            <input
              type="file" accept="image/*" ref={fileInputRef}
              onChange={handleImageChange} className="hidden"
            />

            {/* 图片上传按钮 */}
            <button
              className="p-2 rounded-xl text-ink-muted dark:text-cloud-500 hover:text-sky-500 dark:hover:text-sky-400 hover:bg-sky-50 dark:hover:bg-sky-900/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
              onClick={handlePickImage}
              title="上传图片搜索"
              aria-label="上传图片"
              disabled={loading}
            >
              <Image size={18} />
            </button>

            {/* 文本输入 */}
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
                  // 自动调整高度
                  const el = e.target
                  el.style.height = 'auto'
                  el.style.height = Math.min(el.scrollHeight, 128) + 'px'
                }}
              />
            </div>

            {/* 发送/取消按钮 */}
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

          {/* 模式提示（弱化显示，始终可见） */}
          <div className="flex items-center justify-between mt-2">
            <div className="flex items-center gap-3">
              {canAdjustModes && (
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
              {!canAdjustModes && (
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
