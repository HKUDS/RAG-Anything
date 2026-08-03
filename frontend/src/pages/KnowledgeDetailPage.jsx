import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import {
  Search, Eye, Trash2, X, FileText, Clock, Filter, ZoomIn, ZoomOut, RotateCcw,
  Plus, Layers, Upload, Globe, FolderOpen, ClipboardPaste,
  Loader2, CheckCircle2, XCircle, AlertTriangle, Scissors, ChevronDown, ChevronUp, Zap, Image,
  ArrowLeft, Download, Pencil, Link2, Save, Table, Sigma, Video, ImageIcon, Tag
} from 'lucide-react'
import { loadD3 } from '../utils/lazyD3'
import { motion, AnimatePresence } from 'framer-motion'
import { Link, useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../utils/api'
import ChunkingStrategySelector from '../components/ChunkingStrategySelector'
import { getChunkingStrategyPresentation } from '../utils/chunkingStrategyPresentation'
import { getDocumentTagPresentation } from '../utils/documentTagHealth'
import {
  getDocumentHealth,
  getUploadTaskMessages,
  getUploadTaskStatus,
  isCancellableUploadDocument,
} from '../utils/documentHealth'
import { formatDate } from '../utils/dateFormat'
import SideDrawer from '../components/SideDrawer'
import { UserDialogConfirmation } from '../components/UserDialog'
import TagRelationsPanel from '../components/TagRelationsPanel'
import { useAuth } from '../context/AuthContext'
import {
  createKnowledgeDetailState,
  getDocumentListMode,
  markKnowledgeDetailRefreshing,
  mergeKnowledgeDetailSnapshot,
} from '../utils/knowledgeDetailState'
import {
  GRAPH_DATA_STATUS,
  createGraphDataState,
  graphDataFailed,
  graphDataFromResponses,
  graphDataLoading,
  graphDataSuccess,
} from '../utils/knowledgeDetailGraphState'
import {
  hasActiveUploadTasks,
  shouldPollCoreData,
  tasksTransitionedToTerminal,
} from '../utils/knowledgeDetailPolling'
import { useConfirmedKnowledgeBase } from '../hooks/useConfirmedKnowledgeBase'
import { neutralObjectError } from '../utils/permissionUiPolicy'

const STATUS = {
  queued: 'badge-info',
  processed: 'badge-success',
  processing: 'badge-warning',
  handling: 'badge-info',
  completed: 'badge-success',
  failed: 'badge-error',
  retry_wait: 'badge-warning',
  cancelling: 'badge-warning',
  degraded: 'badge-warning',
}
const STATUS_CN = {
  queued: '排队中',
  processed: '已完成',
  processing: '处理中',
  handling: '入库中',
  completed: '已完成',
  failed: '失败',
  retry_wait: '等待自动重试',
  cancelling: '正在停止并删除',
  degraded: '已入库，图谱待补全',
}
const UPLOAD_TASK_TERMINAL_STATUSES = new Set(['completed', 'processed', 'failed', 'degraded'])
const TAG_TONE_CLASS = {
  success: 'text-sage-600',
  info: 'text-sky-600',
  warning: 'text-amber-600',
  error: 'text-rose-600',
  muted: 'text-ink-muted',
}
const PHASE_CN = {
  initializing: '初始化环境',
  parsing: '解析文档',
  'entity-extraction': '抽取实体',
  embedding: '向量化',
  'graph-building': '构建图谱',
  'multimodal-tasks': '多模态处理',
}
const PHASE_PROGRESS_MODEL = {
  initializing: { start: 4, end: 14, durationMs: 12_000, bufferMs: 700, bufferDrift: 0.8 },
  parsing: { start: 12, end: 34, durationMs: 28_000, bufferMs: 900, bufferDrift: 1.2 },
  'entity-extraction': { start: 36, end: 74, durationMs: 55_000, bufferMs: 1_150, bufferDrift: 1.4 },
  embedding: { start: 56, end: 76, durationMs: 40_000, bufferMs: 950, bufferDrift: 1.1 },
  'graph-building': { start: 78, end: 92, durationMs: 24_000, bufferMs: 850, bufferDrift: 0.9 },
  'multimodal-tasks': { start: 88, end: 97, durationMs: 36_000, bufferMs: 1_300, bufferDrift: 0.8 },
}
const NODE_COLORS = ['#e8734a', '#5b9bd5', '#6b9e7a', '#d4a853', '#c9707e', '#366596', '#6da9d7', '#f08f6d']

function clampProgress(value) {
  return Math.max(0, Math.min(100, value))
}

function parseTaskTimestamp(value) {
  if (!value) return null
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? null : parsed
}

function easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3)
}

function getFileExtension(filename) {
  const raw = typeof filename === 'string' ? filename.trim().toLowerCase() : ''
  const idx = raw.lastIndexOf('.')
  return idx >= 0 ? raw.slice(idx + 1) : ''
}

function getFileSizeTempo(fileSize) {
  const size = Number(fileSize)
  if (!Number.isFinite(size) || size <= 0) return 1

  const sizeKb = size / 1024
  const logFactor = Math.log2(sizeKb + 1)
  return Math.max(0.85, Math.min(2.6, 0.8 + logFactor / 6))
}

function getFileTypeTempo(filename, phaseKey) {
  const ext = getFileExtension(filename)

  const phaseMultiplier = {
    parsing: {
      pdf: 1.55,
      ppt: 1.35,
      pptx: 1.35,
      xls: 1.25,
      xlsx: 1.25,
      doc: 1.08,
      docx: 1.08,
      txt: 0.75,
      md: 0.75,
      csv: 0.8,
      jpg: 0.9,
      jpeg: 0.9,
      png: 0.9,
    },
    'entity-extraction': {
      pdf: 1.2,
      ppt: 1.1,
      pptx: 1.1,
      doc: 1.05,
      docx: 1.05,
      txt: 0.9,
      md: 0.9,
    },
    'graph-building': {
      pdf: 1.1,
      ppt: 1.06,
      pptx: 1.06,
    },
    'multimodal-tasks': {
      pdf: 1.45,
      ppt: 1.3,
      pptx: 1.3,
      doc: 1.12,
      docx: 1.12,
      xls: 1.18,
      xlsx: 1.18,
      jpg: 0.95,
      jpeg: 0.95,
      png: 0.95,
    },
  }

  return phaseMultiplier[phaseKey]?.[ext] ?? 1
}

function getMultimodalStageTempo(task, phaseKey) {
  if (phaseKey !== 'multimodal-tasks') return 1

  const ext = getFileExtension(task.filename)
  const heavyTypes = new Set(['pdf', 'ppt', 'pptx', 'doc', 'docx', 'xls', 'xlsx'])
  return heavyTypes.has(ext) ? 1.4 : 1.22
}

function getPhaseTransitionBuffer(model, tempo) {
  const baseBuffer = model.bufferMs ?? 0
  if (baseBuffer <= 0) return { durationMs: 0, drift: 0 }

  return {
    durationMs: Math.round(baseBuffer * Math.min(1.45, 0.82 + tempo * 0.22)),
    drift: model.bufferDrift ?? 0.8,
  }
}

function getVisualTaskProgress(task, nowMs) {
  if (task.status === 'completed' || task.outcome === 'degraded') return { value: 100, simulated: false }

  if (task.status === 'failed') {
    const failedValue = Number.isFinite(task.progress) ? clampProgress(task.progress) : null
    return { value: failedValue, simulated: false }
  }

  if (task.status !== 'processing') {
    return { value: null, simulated: false }
  }

  const phaseKey = task.phase && PHASE_PROGRESS_MODEL[task.phase] ? task.phase : 'initializing'
  const model = PHASE_PROGRESS_MODEL[phaseKey]
  const anchorMs = parseTaskTimestamp(task.updated_at || task.created_at) ?? nowMs
  const elapsed = Math.max(0, nowMs - anchorMs)
  const tempo = (
    getFileSizeTempo(task.file_size)
    * getFileTypeTempo(task.filename, phaseKey)
    * getMultimodalStageTempo(task, phaseKey)
  )
  const actualValue = Number.isFinite(task.progress) ? clampProgress(task.progress) : null
  const simulatedDuration = model.durationMs * tempo
  const transitionBuffer = getPhaseTransitionBuffer(model, tempo)
  const bufferedStart = Math.min(model.end - 0.5, model.start + transitionBuffer.drift)
  let simulatedValue = model.start

  if (transitionBuffer.durationMs > 0 && elapsed < transitionBuffer.durationMs) {
    const bufferRatio = elapsed / transitionBuffer.durationMs
    simulatedValue = model.start + (bufferedStart - model.start) * easeOutCubic(bufferRatio)
  } else {
    const activeElapsed = Math.max(0, elapsed - transitionBuffer.durationMs)
    const activeRatio = Math.min(1, activeElapsed / Math.max(1, simulatedDuration))
    simulatedValue = bufferedStart + (model.end - bufferedStart) * easeOutCubic(activeRatio)
  }
  const floor = actualValue !== null && actualValue > 0 ? actualValue : model.start

  return {
    value: Math.min(99, clampProgress(Math.max(floor, simulatedValue))),
    simulated: true,
  }
}

// ====================== 上传区域 ======================
function UploadSection({
  kbName,
  onToast,
  chunkingStrategy,
  setChunkingStrategy,
  strategies,
  onUploaded,
  multimodal,
  setMultimodal,
  canWrite = false,
}) {
  const [dragOver, setDragOver] = useState(false)
  const [localFiles, setLocalFiles] = useState([])
  const [serverTasks, setServerTasks] = useState([])
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false)
  const [tasksLoading, setTasksLoading] = useState(false)
  const [tasksLoaded, setTasksLoaded] = useState(false)
  const [tasksError, setTasksError] = useState('')
  const [batchUploading, setBatchUploading] = useState(false)
  const [deletingTaskIds, setDeletingTaskIds] = useState([])
  const [taskDeleteConfirm, setTaskDeleteConfirm] = useState(null)
  const [urlInput, setUrlInput] = useState('')
  const [urlLoading, setUrlLoading] = useState(false)
  const [pasteContent, setPasteContent] = useState('')
  const [pasteTitle, setPasteTitle] = useState('')
  const [folderPath, setFolderPath] = useState('')
  const [folderLoading, setFolderLoading] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const [progressNow, setProgressNow] = useState(() => Date.now())
  const fileInputRef = useRef(null)
  const taskRequestRef = useRef(0)

  const addFiles = useCallback((fileList) => {
    const nextFiles = Array.from(fileList || [])
    if (nextFiles.length === 0) return

    setLocalFiles(prev => {
      const signatures = new Set(prev.map(item => item.signature))
      const additions = []

      nextFiles.forEach(file => {
        const signature = `${file.name}:${file.size}:${file.lastModified}`
        if (signatures.has(signature)) return
        signatures.add(signature)
        additions.push({
          id: `${signature}:${Date.now()}:${Math.random().toString(16).slice(2)}`,
          signature,
          name: file.name,
          size: file.size,
          file,
          submitting: false,
          error: '',
        })
      })

      return additions.length > 0 ? [...prev, ...additions] : prev
    })
  }, [])

  const refreshUploadTasks = useCallback(async ({ silent = false } = {}) => {
    if (!kbName) return
    setCurrentKB(kbName)

    const requestId = ++taskRequestRef.current
    if (!silent) setTasksLoading(true)

    try {
      const result = await api.getUploadTasks()
      if (requestId !== taskRequestRef.current) return
      setServerTasks(result.tasks || [])
      setDeletingTaskIds(previous => previous.filter(id => (
        (result.tasks || []).some(task => task.task_id === id)
      )))
      setTasksError('')
      setTasksLoaded(true)
    } catch (e) {
      if (requestId !== taskRequestRef.current) return
      setTasksError(e.message || '上传任务加载失败')
      setTasksLoaded(true)
    } finally {
      if (!silent && requestId === taskRequestRef.current) setTasksLoading(false)
    }
  }, [kbName])

  useEffect(() => {
    if (!kbName) return
    setCurrentKB(kbName)
    setLocalFiles([])
    setServerTasks([])
    setTasksError('')
    setTasksLoaded(false)
    void refreshUploadTasks()
  }, [kbName, refreshUploadTasks])

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined

    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    const updatePreference = () => setPrefersReducedMotion(mediaQuery.matches)

    updatePreference()

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', updatePreference)
      return () => mediaQuery.removeEventListener('change', updatePreference)
    }

    mediaQuery.addListener(updatePreference)
    return () => mediaQuery.removeListener(updatePreference)
  }, [])

  useEffect(() => {
    if (!showUpload || !kbName) return undefined
    const timer = window.setInterval(() => {
      void refreshUploadTasks({ silent: true })
    }, 3000)
    return () => window.clearInterval(timer)
  }, [kbName, refreshUploadTasks, showUpload])

  useEffect(() => {
    if (!showUpload) return
    setProgressNow(Date.now())
  }, [serverTasks, showUpload])

  useEffect(() => {
    if (!showUpload) return undefined
    const hasActiveProcessing = serverTasks.some(task => task.status === 'processing')
    if (!hasActiveProcessing || prefersReducedMotion) return undefined

    const timer = window.setInterval(() => {
      setProgressNow(Date.now())
    }, 1000)
    return () => window.clearInterval(timer)
  }, [prefersReducedMotion, serverTasks, showUpload])

  const removeLocalFile = useCallback((localId) => {
    setLocalFiles(prev => prev.filter(item => item.id !== localId))
  }, [])

  const submitLocalFile = async (localId) => {
    const target = localFiles.find(item => item.id === localId)
    if (!target || target.submitting) return

    setLocalFiles(prev => prev.map(item => (
      item.id === localId ? { ...item, submitting: true, error: '' } : item
    )))

    try {
      await api.uploadFile(target.file, chunkingStrategy, multimodal)
      setLocalFiles(prev => prev.filter(item => item.id !== localId))
      await refreshUploadTasks({ silent: true })
      onUploaded?.()
      onToast?.(`${target.name} 已加入上传队列`, 'success')
    } catch (e) {
      setLocalFiles(prev => prev.map(item => (
        item.id === localId ? { ...item, submitting: false, error: e.message } : item
      )))
      onToast?.(`${target.name} 上传失败: ${e.message}`, 'error')
    }
  }

  const submitAllFiles = async () => {
    const pendingFiles = localFiles.filter(item => !item.submitting)
    if (pendingFiles.length === 0) return

    const targetIds = new Set(pendingFiles.map(item => item.id))
    setBatchUploading(true)
    setLocalFiles(prev => prev.map(item => (
      targetIds.has(item.id) ? { ...item, submitting: true, error: '' } : item
    )))

    try {
      const result = await api.uploadFiles(
        pendingFiles.map(item => item.file),
        chunkingStrategy,
        multimodal,
      )

      const successCounts = new Map()
      const skippedCounts = new Map()
      ;(result.tasks || []).forEach(task => {
        successCounts.set(task.filename, (successCounts.get(task.filename) || 0) + 1)
      })
      ;(result.skipped || []).forEach(name => {
        skippedCounts.set(name, (skippedCounts.get(name) || 0) + 1)
      })

      setLocalFiles(prev => prev.flatMap(item => {
        if (!targetIds.has(item.id)) return [item]

        const queuedCount = successCounts.get(item.name) || 0
        if (queuedCount > 0) {
          successCounts.set(item.name, queuedCount - 1)
          return []
        }

        const skippedCount = skippedCounts.get(item.name) || 0
        if (skippedCount > 0) {
          skippedCounts.set(item.name, skippedCount - 1)
          return [{ ...item, submitting: false, error: '文件重复或注册失败' }]
        }

        return [{ ...item, submitting: false }]
      }))

      await refreshUploadTasks({ silent: true })
      onUploaded?.()
      const queued = result.tasks?.length || 0
      const skipped = result.skipped?.length || 0
      onToast?.(
        queued > 0
          ? `已提交 ${queued} 个上传任务${skipped > 0 ? `，跳过 ${skipped} 个` : ''}`
          : (result.message || '没有可提交的文件'),
        queued > 0 ? 'success' : 'info',
      )
    } catch (e) {
      setLocalFiles(prev => prev.map(item => (
        targetIds.has(item.id) ? { ...item, submitting: false, error: e.message } : item
      )))
      onToast?.(`批量上传失败: ${e.message}`, 'error')
    } finally {
      setBatchUploading(false)
    }
  }

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setDragOver(false)
    addFiles(e.dataTransfer.files)
  }, [addFiles])

  const handlePaste = async () => {
    if (!pasteContent.trim()) return
    try {
      await api.uploadContent(pasteContent, pasteTitle.trim() || '粘贴内容', chunkingStrategy, multimodal)
      setPasteContent('')
      setPasteTitle('')
      await refreshUploadTasks({ silent: true })
      onUploaded?.()
      onToast?.('文本已上传', 'success')
    } catch (e) {
      onToast?.('粘贴上传失败: ' + e.message, 'error')
    }
  }

  const handleUrlImport = async () => {
    if (!urlInput.trim()) return
    setUrlLoading(true)
    try {
      await api.uploadUrl(urlInput.trim(), { strategy: chunkingStrategy, multimodal })
      setUrlInput('')
      await refreshUploadTasks({ silent: true })
      onUploaded?.()
      onToast?.('URL 导入成功', 'success')
    } catch (e) {
      onToast?.('URL 导入失败: ' + e.message, 'error')
    } finally {
      setUrlLoading(false)
    }
  }

  const handleFolderUpload = async () => {
    if (!folderPath.trim()) return
    setFolderLoading(true)
    try {
      await api.uploadFolder(folderPath.trim(), chunkingStrategy, multimodal)
      setFolderPath('')
      await refreshUploadTasks({ silent: true })
      onUploaded?.()
      onToast?.('文件夹上传成功', 'success')
    } catch (e) {
      onToast?.('文件夹上传失败: ' + e.message, 'error')
    } finally {
      setFolderLoading(false)
    }
  }

  const handleDeleteTask = async (task) => {
    if (!task?.can_delete || !task.task_id) return
    const taskStatus = getUploadTaskStatus(task)
    if (taskStatus === 'processing' || taskStatus === 'retry_wait') {
      setTaskDeleteConfirm(task)
      return
    }
    await confirmDeleteTask(task)
  }

  const confirmDeleteTask = async (task = taskDeleteConfirm) => {
    if (!task?.can_delete || !task.task_id) return
    const taskStatus = getUploadTaskStatus(task)
    setDeletingTaskIds(prev => [...prev, task.task_id])
    try {
      const result = await api.deleteUploadTask(task.task_id)
      setTaskDeleteConfirm(null)
      if (result?.status === 'deleted') {
        setServerTasks(prev => prev.filter(item => item.task_id !== task.task_id))
        setDeletingTaskIds(prev => prev.filter(id => id !== task.task_id))
        onToast?.(`${task.filename} 已删除上传任务`, 'success')
      } else {
        onToast?.(`${task.filename} 正在停止并删除`, 'info')
      }
      await refreshUploadTasks({ silent: true })
    } catch (e) {
      setTaskDeleteConfirm(null)
      onToast?.(e?.status === 409 ? '任务状态已变化，已刷新列表' : `删除上传任务失败: ${e.message}`, e?.status === 409 ? 'info' : 'error')
      await refreshUploadTasks({ silent: true })
    }
  }

  const handleRetryTaskNow = async (task) => {
    try {
      await api.retryUploadTaskNow(task.task_id)
      onToast?.(`${task.filename} 已安排立即重试`, 'success')
      await refreshUploadTasks({ silent: true })
    } catch (e) {
      onToast?.(`立即重试失败: ${e.message}`, 'error')
    }
  }

  const handleCancelRetry = async (task) => {
    try {
      await api.cancelUploadRetry(task.task_id)
      onToast?.(`${task.filename} 已取消自动重试`, 'success')
      await refreshUploadTasks({ silent: true })
    } catch (e) {
      onToast?.(`取消重试失败: ${e.message}`, 'error')
    }
  }

  const pendingLocalCount = localFiles.filter(item => !item.submitting).length
  const uploadSummaryCount = localFiles.length + serverTasks.length

  return (
    <div>
      {canWrite && (
        <button
          onClick={() => setShowUpload(!showUpload)}
          className="flex items-center gap-2 text-xs font-medium text-ink-body hover:text-ink-primary transition-colors"
        >
          {showUpload ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          <Upload size={14} />
          {showUpload ? '收起上传面板' : '展开上传面板'} {uploadSummaryCount > 0 && `(${uploadSummaryCount})`}
        </button>
      )}

      <AnimatePresence>
        {showUpload && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="space-y-4 pt-4">
              <div
                className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors cursor-pointer ${
                  dragOver ? 'border-sky-400 bg-sky-50' : 'border-cloud-300 hover:border-sky-300'
                }`}
                onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload size={24} className="mx-auto mb-2 text-ink-muted" />
                <p className="text-sm text-ink-body font-medium">拖拽文件到此处上传</p>
                <p className="text-xs text-ink-muted mt-1">或点击选择文件</p>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={e => {
                    addFiles(e.target.files)
                    e.target.value = ''
                  }}
                />
              </div>

              <div className="rounded-xl border border-cloud-300/70 bg-cloud-100/70 p-3 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium text-ink-body">本次上传配置</p>
                    <p className="text-2xs text-ink-muted mt-0.5">这些选项只影响本次入库，不会改动平台默认设置。</p>
                  </div>
                  <span className="text-2xs px-2 py-0.5 rounded-full border border-sky-200 bg-sky-50 text-sky-600">
                    仅本次生效
                  </span>
                </div>

                <ChunkingStrategySelector
                  strategies={strategies}
                  value={chunkingStrategy}
                  onChange={setChunkingStrategy}
                  helperText="选择本次上传的文本切分方式，会影响检索效果和处理时间。"
                />

                <div className="flex items-center gap-2 flex-wrap">
                  <Zap size={13} className="text-ink-muted" />
                  <span className="text-xs text-ink-muted">内容识别:</span>
                  {[
                    { key: 'enable_image', label: '识别图片内容' },
                    { key: 'enable_table', label: '解析表格' },
                    { key: 'enable_equation', label: '识别公式' },
                    { key: 'enable_video', label: '处理视频' },
                  ].map(({ key, label }) => (
                    <button
                      key={key}
                      onClick={() => setMultimodal(prev => ({ ...prev, [key]: !prev[key] }))}
                      className={`px-2.5 py-1 rounded-lg text-xs border transition-colors ${
                        multimodal[key]
                          ? 'bg-sky-50 border-sky-300 text-sky-700 font-medium'
                          : 'border-cloud-300 text-ink-muted hover:border-cloud-400'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="card p-3 space-y-2">
                  <div className="flex items-center gap-1.5 text-xs text-ink-muted"><Globe size={12} /> URL 导入</div>
                  <input
                    className="input-field text-xs"
                    placeholder="https://..."
                    value={urlInput}
                    onChange={e => setUrlInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleUrlImport()}
                  />
                  <button className="btn-primary text-xs w-full py-1.5" onClick={handleUrlImport} disabled={urlLoading}>
                    {urlLoading ? <Loader2 size={12} className="animate-spin inline" /> : '导入'}
                  </button>
                </div>
                <div className="card p-3 space-y-2">
                  <div className="flex items-center gap-1.5 text-xs text-ink-muted"><FolderOpen size={12} /> 文件夹导入</div>
                  <input
                    className="input-field text-xs"
                    placeholder={'D:\\docs\\...'}
                    value={folderPath}
                    onChange={e => setFolderPath(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleFolderUpload()}
                  />
                  <button className="btn-primary text-xs w-full py-1.5" onClick={handleFolderUpload} disabled={folderLoading}>
                    {folderLoading ? <Loader2 size={12} className="animate-spin inline" /> : '导入'}
                  </button>
                </div>
                <div className="card p-3 space-y-2">
                  <div className="flex items-center gap-1.5 text-xs text-ink-muted"><ClipboardPaste size={12} /> 粘贴内容</div>
                  <input
                    className="input-field text-xs"
                    placeholder="标题（可选）"
                    value={pasteTitle}
                    onChange={e => setPasteTitle(e.target.value)}
                    maxLength={128}
                  />
                  <textarea
                    className="input-field text-xs h-16 resize-none"
                    placeholder="内容…"
                    value={pasteContent}
                    onChange={e => setPasteContent(e.target.value)}
                  />
                  <button className="btn-primary text-xs w-full py-1.5" onClick={handlePaste} disabled={!pasteContent.trim()}>
                    提交
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="card p-3 space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-medium text-ink-body">待上传文件 ({localFiles.length})</p>
                      <p className="text-2xs text-ink-muted mt-0.5">这里是浏览器里尚未提交到服务器的草稿文件。</p>
                    </div>
                    {pendingLocalCount > 0 && (
                      <button
                        className="btn-primary text-xs py-1 px-3"
                        onClick={submitAllFiles}
                        disabled={batchUploading}
                      >
                        {batchUploading ? '提交中…' : `全部上传 (${pendingLocalCount})`}
                      </button>
                    )}
                  </div>

                  {localFiles.length === 0 ? (
                    <div className="rounded-lg border border-cloud-300/60 bg-cloud-100/60 px-3 py-6 text-center">
                      <p className="text-xs text-ink-muted">还没有待提交文件</p>
                      <p className="text-2xs text-ink-muted mt-1">选择文件后会先出现在这里，提交成功后转入右侧上传任务。</p>
                    </div>
                  ) : (
                    localFiles.map(file => (
                      <div key={file.id} className="rounded-lg border border-cloud-300/60 bg-cloud-100/60 px-3 py-2 text-xs">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 min-w-0">
                              {file.submitting
                                ? <Loader2 size={14} className="animate-spin text-sky-500 shrink-0" />
                                : file.error
                                  ? <XCircle size={14} className="text-rose-500 shrink-0" />
                                  : <FileText size={14} className="text-ink-muted shrink-0" />}
                              <span className="text-ink-body truncate">{file.name}</span>
                            </div>
                            <div className="flex items-center gap-3 mt-1 text-2xs text-ink-muted">
                              <span className="font-mono">{(file.size / 1024).toFixed(0)} KB</span>
                              <span>{file.submitting ? '提交中…' : '待提交'}</span>
                            </div>
                            {file.error && (
                              <p className="mt-1 text-2xs text-rose-500 break-all">{file.error}</p>
                            )}
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            {!file.submitting && (
                              <>
                                <button className="btn-primary text-xs py-0.5 px-2" onClick={() => submitLocalFile(file.id)}>
                                  上传
                                </button>
                                <button className="btn-ghost text-xs py-0.5 px-2 text-rose-500" onClick={() => removeLocalFile(file.id)}>
                                  移除
                                </button>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>

                <div className="card p-3 space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-medium text-ink-body">上传任务 ({serverTasks.length})</p>
                      <p className="text-2xs text-ink-muted mt-0.5">这里展示已经提交到服务器的上传状态，刷新页面后仍可恢复。</p>
                    </div>
                    <button className="btn-ghost text-xs py-1 px-2" onClick={() => refreshUploadTasks()} disabled={tasksLoading}>
                      {tasksLoading ? '刷新中…' : '刷新'}
                    </button>
                  </div>

                  {tasksError && (
                    <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-600">
                      上传任务加载失败: {tasksError}
                    </div>
                  )}

                  {!tasksLoaded && tasksLoading ? (
                    <div className="rounded-lg border border-cloud-300/60 bg-cloud-100/60 px-3 py-6 text-center">
                      <Loader2 size={16} className="animate-spin inline text-sky-500" />
                      <p className="text-xs text-ink-muted mt-2">正在读取上传任务…</p>
                    </div>
                  ) : serverTasks.length === 0 ? (
                    <div className="rounded-lg border border-cloud-300/60 bg-cloud-100/60 px-3 py-6 text-center">
                      <p className="text-xs text-ink-muted">当前没有服务器上传任务</p>
                      <p className="text-2xs text-ink-muted mt-1">已提交的文件会在这里显示排队、处理中、完成或失败状态。</p>
                    </div>
                  ) : (
                    <>
                      {serverTasks.map(task => {
                      const deleting = deletingTaskIds.includes(task.task_id)
                      const taskStatus = getUploadTaskStatus(task)
                      const taskMessages = getUploadTaskMessages(task)
                      const visualProgress = getVisualTaskProgress(task, progressNow)
                      const progressValue = visualProgress.value
                      const taskTimestamp = formatDate(task.updated_at || task.created_at)

                      return (
                        <div key={task.task_id} className="rounded-lg border border-cloud-300/60 bg-cloud-100/60 px-3 py-2 text-xs">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2 min-w-0">
                                {['processing', 'retry_wait', 'cancelling'].includes(taskStatus)
                                  ? <Loader2 size={14} className="animate-spin text-amber-500 shrink-0" />
                                  : taskStatus === 'completed'
                                    ? <CheckCircle2 size={14} className="text-sage-500 shrink-0" />
                                    : taskStatus === 'degraded'
                                      ? <AlertTriangle size={14} className="text-amber-500 shrink-0" />
                                      : taskStatus === 'failed'
                                      ? <XCircle size={14} className="text-rose-500 shrink-0" />
                                      : <Clock size={14} className="text-sky-500 shrink-0" />}
                                <span className="text-ink-body truncate">{task.filename}</span>
                                <span className={STATUS[taskStatus] || 'badge-info'}>
                                  {STATUS_CN[taskStatus] || taskStatus}
                                </span>
                              </div>

                              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-2xs text-ink-muted">
                                {taskTimestamp && (
                                  <span className="flex items-center gap-1">
                                    <Clock size={11} />
                                    {taskTimestamp}
                                  </span>
                                )}
                                {task.phase && (
                                  <span>{PHASE_CN[task.phase] || task.phase}</span>
                                )}
                                {task.chunking_strategy && (
                                  <span className="rounded-md border border-cloud-300 bg-white px-1.5 py-0.5 text-ink-body">
                                    切块：{getChunkingStrategyPresentation(task.chunking_strategy).name}
                                  </span>
                                )}
                                {progressValue !== null && (
                                  <span>进度 {Math.round(progressValue)}%</span>
                                )}
                              </div>

                              {progressValue !== null && (
                                <div className="mt-2 h-1.5 rounded-full bg-cloud-300/70 overflow-hidden">
                                  <div
                                    className={`h-full rounded-full transition-all ${
                                      taskStatus === 'failed'
                                        ? 'bg-rose-400'
                                        : taskStatus === 'degraded'
                                          ? 'bg-amber-400'
                                          : taskStatus === 'completed'
                                          ? 'bg-sage-400'
                                          : visualProgress.simulated
                                            ? `bg-sky-400${prefersReducedMotion ? '' : ' animate-pulse'}`
                                            : 'bg-sky-400'
                                    }`}
                                    style={{ width: `${progressValue}%` }}
                                  />
                                </div>
                              )}

                              {taskMessages.error && (
                                <p className="mt-2 text-2xs text-rose-500 break-all">{taskMessages.error}</p>
                              )}
                              {taskMessages.warning && (
                                <p className="mt-2 flex items-start gap-1 text-2xs text-amber-600 break-all">
                                  <AlertTriangle size={11} className="mt-0.5 shrink-0" />
                                  <span>{taskMessages.warning}</span>
                                </p>
                              )}
                              {taskStatus === 'retry_wait' && task.next_retry_at && (
                                <p className="mt-1 text-2xs text-ink-muted">
                                  下次重试：{formatDate(task.next_retry_at)}
                                </p>
                              )}
                            </div>

                            {canWrite && task.can_delete && (
                              <button
                                className="btn-ghost text-xs py-0.5 px-2 text-rose-500 shrink-0"
                                onClick={() => handleDeleteTask(task)}
                                disabled={deleting}
                                aria-label={`${taskStatus === 'processing' ? '停止并删除' : taskStatus === 'retry_wait' ? '取消重试并删除' : '删除'} ${task.filename}`}
                                title={taskStatus === 'processing' ? '停止并删除上传任务' : taskStatus === 'retry_wait' ? '取消重试并删除上传任务' : '删除上传任务'}
                              >
                                {deleting ? (taskStatus === 'processing' ? '停止中…' : taskStatus === 'retry_wait' ? '取消中…' : '删除中…') : (taskStatus === 'processing' ? '停止并删除' : taskStatus === 'retry_wait' ? '取消重试并删除' : '删除')}
                              </button>
                            )}
                            {canWrite && taskStatus === 'retry_wait' && (
                              <div className="flex shrink-0 gap-1">
                                <button
                                  className="btn-ghost text-xs py-0.5 px-2"
                                  onClick={() => handleRetryTaskNow(task)}
                                  disabled={deleting}
                                  title="立即重试"
                                >
                                  <RotateCcw size={12} />
                                </button>
                                <button
                                  className="btn-ghost text-xs py-0.5 px-2 text-rose-500"
                                  onClick={() => handleCancelRetry(task)}
                                  disabled={deleting}
                                  title="取消自动重试"
                                >
                                  <X size={12} />
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      )
                    })}
                    </>
                  )}
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <UserDialogConfirmation
        isOpen={Boolean(taskDeleteConfirm)}
        title={getUploadTaskStatus(taskDeleteConfirm || {}) === 'processing' ? '停止并删除上传任务' : '取消重试并删除上传任务'}
        description={getUploadTaskStatus(taskDeleteConfirm || {}) === 'processing'
          ? `将停止“${taskDeleteConfirm?.filename || ''}”的后台处理，并删除已生成的内容。此操作无法恢复。`
          : `将取消“${taskDeleteConfirm?.filename || ''}”的自动重试并删除任务。此操作无法恢复。`}
        icon={<Trash2 size={18} />}
        confirmLabel={getUploadTaskStatus(taskDeleteConfirm || {}) === 'processing' ? '停止并删除' : '取消重试并删除'}
        cancelLabel="取消"
        danger
        confirmDisabled={Boolean(taskDeleteConfirm && deletingTaskIds.includes(taskDeleteConfirm.task_id))}
        closeDisabled={Boolean(taskDeleteConfirm && deletingTaskIds.includes(taskDeleteConfirm.task_id))}
        onConfirm={() => void confirmDeleteTask()}
        onCancel={() => setTaskDeleteConfirm(null)}
      />
    </div>
  )
}

// ====================== 主详情页 ======================
export default function KnowledgeDetailPage() {
  const { kbName } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { hasPermission } = useAuth()
  const canManageKB = hasPermission('kb:write')
  const canViewVisionSettings = hasPermission('kb:read')
  const canManageGraph = hasPermission('graph:write')
  const kbAccess = useConfirmedKnowledgeBase(kbName)

  const [detailState, setDetailState] = useState(() => createKnowledgeDetailState(
    kbName,
    null,
  ))
  const [entities, setEntities] = useState([])
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [graphDataState, setGraphDataState] = useState(createGraphDataState)
  const [filter, setFilter] = useState('')
  const [graphSearch, setGraphSearch] = useState('')
  const [detailDoc, setDetailDoc] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [cancellingUploadTaskIds, setCancellingUploadTaskIds] = useState([])
  const [retryingDocIds, setRetryingDocIds] = useState([])
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [reprocessingMultimodal, setReprocessingMultimodal] = useState(false)
  const [selectedNode, setSelectedNode] = useState(null)
  const [nodeDetails, setNodeDetails] = useState(null)
  const [toast, setToast] = useState(null)
  const [chunkingStrategy, setChunkingStrategy] = useState('')
  const [strategies, setStrategies] = useState({})
  // 图谱编辑状态
  const [showCreateNodeModal, setShowCreateNodeModal] = useState(false)
  const [showCreateEdgeModal, setShowCreateEdgeModal] = useState(false)
  const [showDeleteNodeConfirm, setShowDeleteNodeConfirm] = useState(null)
  const [renamingNode, setRenamingNode] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [graphNodeDetail, setGraphNodeDetail] = useState(null)
  // 创建节点表单
  const [newNodeForm, setNewNodeForm] = useState({ name: '', entity_type: '', description: '' })
  // 创建边表单
  const [newEdgeForm, setNewEdgeForm] = useState({ source_entity: '', target_entity: '', relation_type: 'related_to', description: '' })
  const [multimodal, setMultimodal] = useState({
    enable_image: true, enable_table: true, enable_equation: true, enable_video: true
  })
  const [activeTab, setActiveTab] = useState('documents')
  const activeTabRef = useRef(activeTab)
  activeTabRef.current = activeTab
  const [visionSearching, setVisionSearching] = useState(false)
  const [visionResults, setVisionResults] = useState(null)
  const [visionSettings, setVisionSettings] = useState(null)
  const [visionProfiles, setVisionProfiles] = useState([])
  const [visionProfileDraft, setVisionProfileDraft] = useState('')
  const [visionSettingsStatus, setVisionSettingsStatus] = useState({ loading: false, saving: false, error: '', confirmReindex: false })
  const visionInputRef = useRef()
  const svgRef = useRef()
  const graphContainerRef = useRef()
  const zoomRef = useRef(null)
  const prevGraphFingerprint = useRef('')
  const prevGraphSearch = useRef('')
  const genRef = useRef(0)
  const graphGenRef = useRef(0)
  const activeKBRef = useRef(kbName)
  activeKBRef.current = kbName
  const loadAbortRef = useRef(null)
  const graphLoadAbortRef = useRef(null)
  const nodeDetailAbortRef = useRef(null)
  const visionRequestRef = useRef(0)
  const selectedNodeRef = useRef(null)
  selectedNodeRef.current = selectedNode
  const simRef = useRef(null)
  const cachedDetailForRoute = useMemo(
    () => kbAccess.confirmed ? api.getCachedKnowledgeDetail(kbName) : null,
    [kbAccess.confirmed, kbName],
  )
  const displayedDetailState = detailState.kbName === kbName
    ? detailState
    : createKnowledgeDetailState(kbName, cachedDetailForRoute)
  const docs = displayedDetailState.documents.data
  const stats = displayedDetailState.stats.data

  useEffect(() => {
    const requested = searchParams.get('tab')
    setActiveTab(['documents', 'graph', 'tags'].includes(requested) ? requested : 'documents')
  }, [searchParams])

  useEffect(() => {
    if (!kbAccess.confirmed || !canViewVisionSettings) return undefined
    let active = true
    setVisionSettingsStatus({ loading: true, saving: false, error: '', confirmReindex: false })
    Promise.all([api.getKBVisionSettings(kbName), api.listModelProfiles('embedding')])
      .then(([settings, catalog]) => {
        if (!active) return
        const state = settings?.vision_embedding || {}
        setVisionSettings(state)
        setVisionProfileDraft(state.index_state === 'failed' ? (state.target_profile_id || state.profile_id || '') : (state.profile_id || ''))
        setVisionProfiles(catalog?.profiles || [])
        setVisionSettingsStatus(current => ({ ...current, loading: false }))
      })
      .catch(error => {
        if (active) setVisionSettingsStatus(current => ({ ...current, loading: false, error: error.message || '视觉向量设置加载失败' }))
      })
    return () => { active = false }
  }, [kbAccess.confirmed, kbName, canViewVisionSettings])

  useEffect(() => {
    if (!kbAccess.confirmed || !canViewVisionSettings || visionSettings?.index_state !== 'reindexing') return undefined
    let active = true
    const refresh = async () => {
      try {
        const settings = await api.getKBVisionSettings(kbName)
        if (!active) return
        const state = settings?.vision_embedding || {}
        setVisionSettings(state)
        setVisionSettingsStatus(current => ({ ...current, error: '' }))
        if (state.index_state !== 'reindexing') {
          setVisionProfileDraft(state.index_state === 'failed' ? (state.target_profile_id || state.profile_id || '') : (state.profile_id || ''))
          showToast(state.index_state === 'failed' ? '视觉向量索引重建失败，可重新选择后重试' : '视觉向量索引重建完成', state.index_state === 'failed' ? 'error' : 'success')
        }
      } catch (error) {
        if (active) setVisionSettingsStatus(current => ({ ...current, error: error.message || '视觉向量重建状态刷新失败' }))
      }
    }
    const timer = window.setInterval(refresh, 3000)
    void refresh()
    return () => { active = false; window.clearInterval(timer) }
  }, [kbAccess.confirmed, kbName, canViewVisionSettings, visionSettings?.index_state])

  const selectTab = useCallback((tab) => {
    const next = new URLSearchParams(searchParams)
    if (tab === 'documents') next.delete('tab')
    else next.set('tab', tab)
    if (tab !== 'tags') next.delete('tag')
    setSearchParams(next)
  }, [searchParams, setSearchParams])

  const selectTag = useCallback((tagId) => {
    const next = new URLSearchParams(searchParams)
    next.set('tab', 'tags')
    next.set('tag', tagId)
    setSearchParams(next)
  }, [searchParams, setSearchParams])

  // ── 图谱编辑处理 ──

  const handleCreateNode = async () => {
    if (!canManageGraph) return
    if (!newNodeForm.name.trim()) return
    try {
      await api.createGraphNode(newNodeForm, { kb: kbName })
      setShowCreateNodeModal(false)
      setNewNodeForm({ name: '', entity_type: '', description: '' })
      await loadKBData({ force: true })
      await loadGraphData({ silent: true })
      showToast(`实体 "${newNodeForm.name}" 已创建`, 'success')
    } catch (e) { showToast('创建失败: ' + e.message, 'error') }
  }

  const handleRenameNode = async (oldName) => {
    if (!canManageGraph) return
    if (!renameValue.trim() || renameValue.trim() === oldName) {
      setRenamingNode(null); return
    }
    try {
      await api.renameGraphNode(oldName, renameValue.trim(), { kb: kbName })
      setRenamingNode(null); setSelectedNode(null); setNodeDetails(null)
      await loadKBData({ force: true })
      await loadGraphData({ silent: true })
      showToast(`已重命名为 "${renameValue.trim()}"`, 'success')
    } catch (e) { showToast('重命名失败: ' + e.message, 'error') }
  }

  const handleDeleteNode = async (name) => {
    if (!canManageGraph) return
    try {
      await api.deleteGraphNode(name, { kb: kbName })
      setShowDeleteNodeConfirm(null); setSelectedNode(null); setNodeDetails(null)
      await loadKBData({ force: true })
      await loadGraphData({ silent: true })
      showToast(`实体 "${name}" 已删除`, 'success')
    } catch (e) { showToast('删除失败: ' + e.message, 'error') }
  }

  const handleCreateEdge = async () => {
    if (!canManageGraph) return
    if (!newEdgeForm.source_entity.trim() || !newEdgeForm.target_entity.trim()) return
    try {
      await api.createGraphEdge(newEdgeForm, { kb: kbName })
      setShowCreateEdgeModal(false)
      setNewEdgeForm({ source_entity: '', target_entity: '', relation_type: 'related_to', description: '' })
      await loadKBData({ force: true })
      await loadGraphData({ silent: true })
      showToast('关系已创建', 'success')
    } catch (e) { showToast('创建关系失败: ' + e.message, 'error') }
  }

  const handleDeleteEdge = async (edgeId) => {
    if (!canManageGraph) return
    try {
      await api.deleteGraphEdge(edgeId, { kb: kbName })
      await loadKBData({ force: true })
      await loadGraphData({ silent: true })
      showToast('关系已删除', 'success')
    } catch (e) { showToast('删除关系失败: ' + e.message, 'error') }
  }

  // 从接口获取节点详细信息
  const fetchNodeDetail = useCallback(async (nodeName) => {
    const requestKB = kbName
    nodeDetailAbortRef.current?.abort()
    const controller = new AbortController()
    nodeDetailAbortRef.current = controller
    try {
      const detail = await api.getGraphNodeForKB(requestKB, nodeName, { signal: controller.signal })
      if (controller.signal.aborted || requestKB !== activeKBRef.current) return
      setGraphNodeDetail(detail)
    } catch (error) {
      if (error?.name !== 'AbortError') setGraphNodeDetail(null)
    }
  }, [kbName])

  // 辅助函数：D3 forceLink 会把边的 source/target 从字符串改成节点对象。
  // 仿真后 edge.source 变为 {id, x, y, ...}，不再是裸字符串。
  // 该函数无论边处于哪种状态，都能提取字符串 ID。
  const _sid = (edge, prop) => {
    const v = edge[prop]
    return v && typeof v === 'object' ? v.id : v
  }

  // 挂载或参数变化时设置当前知识库
  useEffect(() => {
    if (!kbAccess.confirmed) return
    loadAbortRef.current?.abort()
    nodeDetailAbortRef.current?.abort()
    graphLoadAbortRef.current?.abort()
    graphGenRef.current += 1
    setDetailState(createKnowledgeDetailState(kbName, api.getCachedKnowledgeDetail(kbName)))
    setEntities([])
    setGraph({ nodes: [], edges: [] })
    setGraphDataState(createGraphDataState())
    setFilter('')
    setGraphSearch('')
    setDetailDoc(null)
    setDeleteConfirm(null)
    setRetryingDocIds([])
    setCancellingUploadTaskIds([])
    setSelectedIds(new Set())
    setSelectedNode(null)
    setNodeDetails(null)
    setGraphNodeDetail(null)
    setShowCreateNodeModal(false)
    setShowCreateEdgeModal(false)
    setShowDeleteNodeConfirm(null)
    setRenamingNode(null)
    setRenameValue('')
    setNewNodeForm({ name: '', entity_type: '', description: '' })
    setNewEdgeForm({ source_entity: '', target_entity: '', relation_type: 'related_to', description: '' })
    setVisionSearching(false)
    setVisionResults(null)
    visionRequestRef.current += 1
    prevGraphFingerprint.current = ''
    prevGraphSearch.current = ''
  }, [kbAccess.confirmed, kbName])

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  // 加载设置（分块策略），仅执行一次
  useEffect(() => {
    api.getPersonalSettings().then(r => {
      const ingestion = r?.effective?.ingestion || {}
      setChunkingStrategy(ingestion.chunking_strategy || '')
      setMultimodal({
        enable_image: ingestion.enable_image ?? true,
        enable_table: ingestion.enable_table ?? true,
        enable_equation: ingestion.enable_equation ?? true,
        enable_video: ingestion.enable_video ?? false,
      })
    }).catch(() => {})
  }, [])

  // 文档/统计核心数据加载；每个响应都绑定显式 KB、abort 与 generation。
  // 图谱/实体数据由 loadGraphData 在图谱 tab 激活时按需加载。
  const loadKBData = useCallback(async ({ force = false, silent = false } = {}) => {
    if (!kbAccess.confirmed) return
    const requestKB = kbName
    const gen = ++genRef.current
    loadAbortRef.current?.abort()
    const controller = new AbortController()
    loadAbortRef.current = controller

    setDetailState(previous => {
      const base = previous.kbName === requestKB
        ? previous
        : createKnowledgeDetailState(requestKB, api.getCachedKnowledgeDetail(requestKB))
      const hasVisibleData = base.documents.status === 'ready' || base.stats.status === 'ready'
      return silent || hasVisibleData ? markKnowledgeDetailRefreshing(base) : base
    })

    try {
      const detail = await api.prefetchKnowledgeDetail(
        requestKB,
        { force, signal: controller.signal, timeoutMs: 6_000 },
      )
      if (controller.signal.aborted || gen !== genRef.current || requestKB !== activeKBRef.current) return
      const normalizeResource = resource => resource?.status === 'error'
        ? { ...resource, error: neutralObjectError(resource.httpStatus === 403, resource.httpStatus === 404, resource.error) }
        : resource
      setDetailState(previous => mergeKnowledgeDetailSnapshot(previous, requestKB, {
        ...detail,
        documents: normalizeResource(detail.documents),
        stats: normalizeResource(detail.stats),
      }))
    } catch (error) {
      if (controller.signal.aborted || gen !== genRef.current || requestKB !== activeKBRef.current) return
      if (error?.name === 'AbortError') return
      const message = neutralObjectError(error?.status === 403, error?.status === 404, error?.message || '加载失败，请重试')
      setDetailState(previous => mergeKnowledgeDetailSnapshot(previous, requestKB, {
        documents: { status: 'error', error: message },
        stats: { status: 'error', error: message },
      }))
    } finally {
      if (loadAbortRef.current === controller) loadAbortRef.current = null
    }
  }, [kbAccess.confirmed, kbName])

  // 合并实体名称列表，用于创建边时自动补全（对 graph.nodes 与 entities 去重）
  const allEntityNames = useMemo(() => {
    const nameSet = new Set()
    entities.forEach(e => { if (e.name) nameSet.add(e.name) })
    graph.nodes.forEach(n => { if (n.id) nameSet.add(n.id) })
    return [...nameSet].sort()
  }, [entities, graph.nodes])

  // 图谱/实体数据按需加载：仅在图谱 tab 激活时请求，切走不重置，失败可重试。
  const loadGraphData = useCallback(async ({ silent = false } = {}) => {
    if (!kbAccess.confirmed) return
    const requestKB = kbName
    const gen = ++graphGenRef.current
    graphLoadAbortRef.current?.abort()
    const controller = new AbortController()
    graphLoadAbortRef.current = controller

    if (!silent) {
      setGraphDataState(previous => graphDataLoading(previous))
    }

    try {
      const [entitiesResult, graphResult] = await Promise.allSettled([
        api.getEntitiesForKB(requestKB, 200, { signal: controller.signal }),
        api.getGraphForKB(requestKB, { signal: controller.signal }),
      ])
      if (controller.signal.aborted || gen !== graphGenRef.current || requestKB !== activeKBRef.current) return

      if (entitiesResult.status === 'rejected' || graphResult.status === 'rejected') {
        const error = entitiesResult.reason?.message || graphResult.reason?.message || '图谱数据加载失败'
        setGraphDataState(previous => graphDataFailed(previous, error, { preserveReady: silent }))
        return
      }
      const data = graphDataFromResponses(entitiesResult.value, graphResult.value)
      setEntities(data.entities)
      setGraph(data.graph)
      setGraphDataState(graphDataSuccess())
    } catch (error) {
      if (controller.signal.aborted || gen !== graphGenRef.current || requestKB !== activeKBRef.current) return
      if (error?.name === 'AbortError') return
      setGraphDataState(previous => graphDataFailed(previous, error?.message || '图谱数据加载失败', { preserveReady: silent }))
    } finally {
      if (graphLoadAbortRef.current === controller) graphLoadAbortRef.current = null
    }
  }, [kbAccess.confirmed, kbName])

  // 图谱 tab 首次激活时触发一次加载（切走不重置，之后由轮询/编辑操作负责刷新）
  useEffect(() => {
    if (activeTab !== 'graph' || graphDataState.status !== GRAPH_DATA_STATUS.IDLE) return
    void loadGraphData()
  }, [activeTab, graphDataState.status, loadGraphData])

  // 挂载时加载核心数据（文档/统计，走 prefetch 缓存）
  useEffect(() => {
    if (!kbAccess.confirmed) return
    loadKBData()
    return () => {
      loadAbortRef.current?.abort()
      nodeDetailAbortRef.current?.abort()
      graphLoadAbortRef.current?.abort()
    }
  }, [kbAccess.confirmed, kbName, loadKBData])

  // 任务感知轮询：15s 一次。每个 tick 先刷新上传任务快照作为门控（不复用面板冻结的
  // serverTasks）：存在非终态任务才刷新核心数据；图谱 tab 激活时顺带刷新实体/图谱；
  // 任务从非终态转为全部终态时执行最后一次 loadKBData 同步文档列表；页面隐藏时暂停，
  // 恢复可见立即检查一次。interval 保持运行以感知后续新上传任务。
  useEffect(() => {
    if (!kbAccess.confirmed) return
    let disposed = false
    let running = false
    let prevTasks = []
    let interval = null

    const runTick = async () => {
      if (disposed || running || document.visibilityState === 'hidden') return
      running = true
      try {
        const response = await api.getUploadTasks()
        if (disposed || activeKBRef.current !== kbName) return
        const tasks = response?.tasks || []
        const hasActive = hasActiveUploadTasks(tasks)
        const transitionedToTerminal = tasksTransitionedToTerminal(prevTasks, tasks)
        prevTasks = tasks

        if (!shouldPollCoreData({ visible: true, hasActiveUploads: hasActive, activeTab: activeTabRef.current })) {
          if (transitionedToTerminal) {
            await loadKBData({ force: true, silent: true })
          }
          return
        }
        await loadKBData({ force: true, silent: true })
        if (activeTabRef.current === 'graph') {
          await loadGraphData({ silent: true })
        }
      } catch (_) {
        // 单个 tick 失败不中断轮询，等待下一周期重试。
      } finally {
        running = false
      }
    }

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void runTick()
    }

    interval = window.setInterval(() => void runTick(), 15_000)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      disposed = true
      if (interval) window.clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [kbAccess.confirmed, kbName, loadKBData, loadGraphData])

  useEffect(() => {
    if (!kbAccess.confirmed || cancellingUploadTaskIds.length === 0) return undefined
    let disposed = false

    const pollCancellation = async () => {
      try {
        const response = await api.getUploadTasks()
        if (disposed || activeKBRef.current !== kbName) return
        const taskById = new Map((response.tasks || []).map(task => [task.task_id, task]))
        const unresolved = []
        let needsRefresh = false
        let terminalCount = 0

        cancellingUploadTaskIds.forEach(taskId => {
          const task = taskById.get(taskId)
          if (!task) {
            needsRefresh = true
            return
          }
          if (UPLOAD_TASK_TERMINAL_STATUSES.has(getUploadTaskStatus(task))) {
            needsRefresh = true
            terminalCount += 1
            return
          }
          unresolved.push(taskId)
        })

        setCancellingUploadTaskIds(previous => (
          previous.length === unresolved.length
          && previous.every((taskId, index) => taskId === unresolved[index])
            ? previous
            : unresolved
        ))
        if (terminalCount) setToast({ msg: '上传任务状态已变化，未完成删除，请刷新后重试', type: 'info' })
        if (needsRefresh) await loadKBData({ force: true })
      } catch (_) {
        // Keep the row in its cancellation state and retry on the next interval.
      }
    }

    void pollCancellation()
    const interval = setInterval(() => void pollCancellation(), 2000)
    return () => {
      disposed = true
      clearInterval(interval)
    }
  }, [kbAccess.confirmed, kbName, cancellingUploadTaskIds, loadKBData])

  // D3 图谱
  const drawGraph = useCallback(async () => {
    if (!svgRef.current) return
    if (!graph.nodes.length) {
      svgRef.current.innerHTML = ''
      if (simRef.current) { simRef.current.stop(); simRef.current = null }
      zoomRef.current = null
      return
    }

    try {
      const d3 = await loadD3()
      if (!svgRef.current) return
      if (simRef.current) { simRef.current.stop(); simRef.current = null }

      const svg = d3.select(svgRef.current)
      const savedTransform = zoomRef.current
        ? d3.zoomTransform(svg.node())
        : d3.zoomIdentity

      svg.selectAll('*').remove()

      let displayNodes = [...graph.nodes]
      if (graphSearch.trim()) {
        const q = graphSearch.toLowerCase()
        displayNodes = displayNodes.filter(n => n.label?.toLowerCase().includes(q) || n.id?.toLowerCase().includes(q))
        const matchedIds = new Set(displayNodes.map(n => n.id))
        graph.edges.forEach(e => {
          if (matchedIds.has(e.source) && !matchedIds.has(e.target)) {
            const n = graph.nodes.find(x => x.id === e.target)
            if (n) { displayNodes.push(n); matchedIds.add(n.id) }
          }
          if (matchedIds.has(e.target) && !matchedIds.has(e.source)) {
            const n = graph.nodes.find(x => x.id === e.source)
            if (n) { displayNodes.push(n); matchedIds.add(n.id) }
          }
        })
      } else {
        displayNodes.sort((a, b) => (b.degree || 0) - (a.degree || 0))
        displayNodes = displayNodes.slice(0, 200)
      }
      const displayIds = new Set(displayNodes.map(n => n.id))
      const displayEdges = graph.edges.filter(e => displayIds.has(e.source) && displayIds.has(e.target))

      const W = graphContainerRef.current?.clientWidth || 600
      const H = 420
      const svgEl = svg.attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%').attr('height', H)
      const g = svgEl.append('g')
      const zoom = d3.zoom()
        .scaleExtent([0.3, 4])
        .filter((event) => {
          // 允许任意位置滚轮/双击缩放，仅允许在 SVG 背景上拖动画布
          if (event.type === 'wheel' || event.type === 'dblclick') return true
          return event.target === svgRef.current
        })
        .on('zoom', (e) => g.attr('transform', e.transform))
      svgEl.call(zoom)
      svgEl.call(zoom.transform, savedTransform)
      zoomRef.current = zoom

      const colorScale = d3.scaleOrdinal(NODE_COLORS)
      const sizeScale = d3.scaleSqrt().domain([0, d3.max(displayNodes, d => d.degree) || 1]).range([5, 18])

      const sim = d3.forceSimulation(displayNodes)
        .force('link', d3.forceLink(displayEdges).id(d => d.id).distance(d => 80 / Math.sqrt((d.source.degree || 1) + 1)))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(W / 2, H / 2))
        .force('collision', d3.forceCollide().radius(d => sizeScale(d.degree) + 8))
      simRef.current = sim

      const link = g.append('g').selectAll('line').data(displayEdges).join('line')
        .attr('stroke', '#bcd3e8').attr('stroke-width', 0.5).attr('stroke-opacity', 0.6)
      const edgeLabels = g.append('g').selectAll('text').data(displayEdges.slice(0, 15)).join('text')
        .text(d => (d.label || '').slice(0, 10)).attr('font-size', 7).attr('fill', '#557a95').attr('text-anchor', 'middle')

      const nodeGroup = g.append('g').selectAll('g').data(displayNodes).join('g').attr('cursor', 'pointer')
        .call(d3.drag().on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
          .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
          .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null }))

      nodeGroup.append('circle').attr('r', d => sizeScale(d.degree)).attr('fill', d => colorScale(d.id))
        .attr('stroke', '#d6e5f2').attr('stroke-width', 1).attr('opacity', 0.85)
      nodeGroup.append('text')
        .text(d => (d.label || d.id || '').slice(0, 10))
        .attr('font-size', d => Math.max(7, Math.min(11, (sizeScale(d.degree) || 5) * 0.7)))
        .attr('fill', '#2d4d66').attr('text-anchor', 'middle').attr('dy', d => sizeScale(d.degree) + 12)
        .attr('font-family', "'Microsoft YaHei', 'SimHei', sans-serif")

      nodeGroup.on('click', async (e, d) => {
        e.stopPropagation(); setSelectedNode(d)
        const connections = graph.edges.filter(e => _sid(e, 'source') === d.id || _sid(e, 'target') === d.id)
        const connectedNames = new Set(); const connectionList = []
        connections.forEach(e => {
          const other = _sid(e, 'source') === d.id ? _sid(e, 'target') : _sid(e, 'source')
          connectedNames.add(other)
          connectionList.push({ other, label: e.label || '', direction: _sid(e, 'source') === d.id ? '→' : '←', _userRelationId: e._user_relation_id || '' })
        })
        setNodeDetails({
          node: d, connections: connectionList.slice(0, 30),
          connectedNodes: graph.nodes.filter(n => connectedNames.has(n.id)).slice(0, 20),
          totalConnections: connectionList.length,
        })
        // 从后端获取更完整的详情
        fetchNodeDetail(d.id)

        // 平滑居中到被点击节点
        if (d.x !== undefined && d.y !== undefined) {
          const currentTransform = d3.zoomTransform(svg.node())
          const targetX = W / 2 - d.x * currentTransform.k
          const targetY = H / 2 - d.y * currentTransform.k
          svg.transition().duration(400).call(
            zoom.transform,
            d3.zoomIdentity.translate(targetX, targetY).scale(currentTransform.k)
          )
        }
      })
      svgEl.on('click', () => { setSelectedNode(null); setNodeDetails(null) })

      const selNode = selectedNodeRef.current
      if (selNode) {
        nodeGroup.select('circle').attr('opacity', d => d.id === selNode.id ? 1 : 0.3)
        link.attr('stroke-opacity', d => d.source.id === selNode.id || d.target.id === selNode.id ? 0.9 : 0.15)
      }
      sim.on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y)
        edgeLabels.attr('x', d => (d.source.x + d.target.x) / 2).attr('y', d => (d.source.y + d.target.y) / 2)
        nodeGroup.attr('transform', d => `translate(${d.x},${d.y})`)
      })
    } catch(e) { console.warn('D3 error:', e) }
  }, [graph, graphSearch])

  // 图谱副作用：通过指纹控制触发
  useEffect(() => {
    if (activeTab !== 'graph') {
      const svg = svgRef.current
      if (svg) svg.innerHTML = ''
      if (simRef.current) { simRef.current.stop(); simRef.current = null }
      zoomRef.current = null
      prevGraphFingerprint.current = ''
      prevGraphSearch.current = ''
      return
    }
    if (prevGraphFingerprint.current === '') {
      prevGraphFingerprint.current = JSON.stringify(graph)
      prevGraphSearch.current = graphSearch
      void drawGraph()
      return
    }
    const fp = prevGraphFingerprint.current + '|' + prevGraphSearch.current
    const newFp = JSON.stringify(graph) + '|' + graphSearch
    if (fp !== newFp) {
      prevGraphFingerprint.current = JSON.stringify(graph)
      prevGraphSearch.current = graphSearch
      void drawGraph()
    }
  }, [graph, graphSearch, drawGraph, activeTab])

  useEffect(() => {
    return () => { if (simRef.current) simRef.current.stop() }
  }, [])

  useEffect(() => {
    if (!selectedNode || activeTab !== 'entities') return
    let cancelled = false
    void loadD3().then(d3 => {
      if (cancelled || !svgRef.current) return
      try {
        const svg = d3.select(svgRef.current)
        if (svg.empty()) return
        svg.selectAll('circle').attr('opacity', function () {
          const pg = this.parentNode
          if (!pg) return 0.85
          const parentData = d3.select(pg).datum()
          return parentData?.id === selectedNode.id ? 1 : 0.3
        })
        svg.selectAll('line').attr('stroke-opacity', function (d) {
          if (!d) return 0.6
          const sourceId = d.source?.id ?? d.source
          const targetId = d.target?.id ?? d.target
          return sourceId === selectedNode.id || targetId === selectedNode.id ? 0.9 : 0.15
        })
      } catch (_) { /* SVG 尚未渲染 */ }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [selectedNode, activeTab])

  const handleZoom = async (dir) => {
    if (!svgRef.current) return
    try {
      const d3 = await loadD3()
      if (!svgRef.current || !zoomRef.current) return
      const svg = d3.select(svgRef.current)
      if (dir === 'in') svg.transition().call(zoomRef.current.scaleBy, 1.5)
      else if (dir === 'out') svg.transition().call(zoomRef.current.scaleBy, 0.7)
      else svg.transition().call(zoomRef.current.transform, d3.zoomIdentity)
    } catch { /* zoom controls unavailable until graph chunk loads */ }
  }

  const filteredDocs = displayedDetailState.documents.status === 'ready'
    ? docs.filter(d => d.file?.toLowerCase().includes(filter.toLowerCase()))
    : []
  const documentListMode = getDocumentListMode({
    routeKB: kbName,
    state: displayedDetailState,
    filteredCount: filteredDocs.length,
    hasFilter: Boolean(filter.trim()),
  })

  const handleRetryDocument = async (doc) => {
    if (!canManageKB) return
    if (!doc?.id || retryingDocIds.includes(doc.id)) return
    setRetryingDocIds(prev => [...prev, doc.id])
    try {
      await api.retryDocument(doc.id, { kb: kbName })
      showToast(
        getDocumentHealth(doc) === 'degraded' ? '图谱补偿已提交' : '文档重试已提交',
        'success',
      )
      await loadKBData({ force: true })
    } catch (e) {
      showToast('提交重试失败: ' + e.message, 'error')
    } finally {
      setRetryingDocIds(prev => prev.filter(id => id !== doc.id))
    }
  }

  const handleDelete = async () => {
    if (!canManageKB) return
    const documentToDelete = deleteConfirm
    if (!documentToDelete) return
    const uploadTaskId = documentToDelete.upload_task_id
    const deleteUploadTask = isCancellableUploadDocument(documentToDelete)

    const removeDocumentFromList = () => {
      setDetailState(previous => ({
        ...previous,
        documents: {
          ...previous.documents,
          data: previous.documents.data.filter(doc => doc.id !== documentToDelete.id),
        },
      }))
      setSelectedIds(prev => {
        if (!prev.has(documentToDelete.id)) return prev
        const next = new Set(prev)
        next.delete(documentToDelete.id)
        return next
      })
      setDeleteConfirm(null)
    }

    setDeleting(true)
    try {
      const result = deleteUploadTask
        ? await api.deleteUploadTask(uploadTaskId)
        : await api.deleteDocument(documentToDelete.id, { kb: kbName })
      if (deleteUploadTask && result?.status === 'cancelling') {
        setDetailState(previous => ({
          ...previous,
          documents: {
            ...previous.documents,
            data: previous.documents.data.map(doc => (
              doc.id === documentToDelete.id
                ? { ...doc, status: 'cancelling', raw_status: 'cancelling', health: 'cancelling' }
                : doc
            )),
          },
        }))
        setCancellingUploadTaskIds(previous => (
          previous.includes(uploadTaskId) ? previous : [...previous, uploadTaskId]
        ))
        setDeleteConfirm(null)
        showToast(`${documentToDelete.file} 正在停止并删除`, 'info')
        await loadKBData({ force: true })
        return
      }
      removeDocumentFromList()
      showToast(
        deleteUploadTask ? `${documentToDelete.file} 已删除上传任务` : `${documentToDelete.file} 已从列表移除`,
        'success',
      )
      await loadKBData({ force: true })
    } catch (e) {
      if (!deleteUploadTask && e?.status === 404) {
        removeDocumentFromList()
        showToast(`${documentToDelete.file} 已不存在，已从列表移除`, 'info')
        await loadKBData({ force: true })
        return
      }
      if (deleteUploadTask && (e?.status === 404 || e?.status === 409)) {
        setDeleteConfirm(null)
        showToast('上传任务状态已变化，已刷新列表', 'info')
        await loadKBData({ force: true })
        return
      }
      showToast('删除失败: ' + e.message, 'error')
    } finally {
      setDeleting(false)
    }
  }

  const toggleSelect = (id) => {
    if (!canManageKB) return
    setSelectedIds(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next })
  }
  const toggleSelectAll = () => {
    if (!canManageKB) return
    setSelectedIds(prev => prev.size === filteredDocs.length ? new Set() : new Set(filteredDocs.map(d => d.id)))
  }

  const handleBatchDelete = async () => {
    if (!canManageKB) return
    setBatchDeleting(true)
    try {
      const res = await api.deleteDocuments([...selectedIds], { kb: kbName })
      setSelectedIds(new Set())
      await loadKBData({ force: true })
      showToast(`已删除 ${res.total_deleted} 个文档`, 'success')
    } catch(e) { showToast('批量删除失败: ' + e.message, 'error') }
    setBatchDeleting(false)
  }

  const handleReprocessMultimodal = async () => {
    if (!canManageKB || !kbName) return
    setReprocessingMultimodal(true)
    try {
      const result = await api.reprocessMultimodal(kbName)
      showToast(result.message || '多模态补处理已提交', result.status === 'ok' ? 'success' : 'info')
      await loadKBData({ force: true })
    } catch (e) {
      showToast('多模态补处理失败: ' + e.message, 'error')
    } finally {
      setReprocessingMultimodal(false)
    }
  }

  const handleImageSearch = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const requestKB = kbName
    const requestId = ++visionRequestRef.current
    setVisionSearching(true)
    setVisionResults(null)
    try {
      const res = await api.imageSearchForKB(requestKB, file, 10)
      if (requestId !== visionRequestRef.current || requestKB !== activeKBRef.current) return
      setVisionResults(res)
      showToast(`找到 ${res.count} 个相似图片`, 'success')
    } catch (err) {
      if (requestId !== visionRequestRef.current || requestKB !== activeKBRef.current) return
      showToast('图片搜索失败: ' + err.message, 'error')
    } finally {
      if (requestId === visionRequestRef.current && requestKB === activeKBRef.current) setVisionSearching(false)
      if (visionInputRef.current) visionInputRef.current.value = ''
    }
  }

  const retryFailedReindex = visionSettings?.index_state === 'failed'
    && visionProfileDraft === visionSettings?.target_profile_id

  const saveVisionProfile = async () => {
    if (!canManageKB || !visionProfileDraft || visionSettingsStatus.saving) return
    setVisionSettingsStatus(current => ({ ...current, saving: true, error: '' }))
    try {
      const result = await api.updateKBVisionSettings(kbName, {
        profile_id: visionProfileDraft,
        reindex: visionSettingsStatus.confirmReindex || retryFailedReindex,
      })
      const state = result?.vision_embedding || (result?.task_id ? {
        ...visionSettings,
        index_state: 'reindexing',
        target_profile_id: visionProfileDraft,
        task: { id: result.task_id, status: result.status || 'queued', progress: 0 },
      } : visionSettings)
      setVisionSettings(state)
      setVisionSettingsStatus(current => ({ ...current, saving: false, confirmReindex: false }))
      showToast(result?.task_id ? '视觉向量索引重建已加入队列' : '视觉向量模型已更新', 'success')
    } catch (error) {
      const needsReindex = error.status === 409 && error.detail?.code === 'reindex_required'
      setVisionSettingsStatus(current => ({
        ...current,
        saving: false,
        confirmReindex: needsReindex,
        error: needsReindex
          ? '当前知识库已有视觉向量。确认后将在后台并行重建，查询期间继续使用旧索引。'
          : (error.message || '视觉向量模型更新失败'),
      }))
    }
  }

  const visionIndexStatus = visionSettings?.index_state === 'reindexing'
    ? `重建中 ${Math.round((visionSettings.task?.progress || 0) * 100)}%`
    : visionSettings?.index_state === 'failed'
      ? '最近一次重建失败，旧索引仍在使用'
      : '索引可用'

  if (kbAccess.loading) {
    return <div className="py-24 text-center" role="status"><Loader2 size={28} className="mx-auto animate-spin text-sky-500" /><p className="mt-3 text-sm text-ink-muted">正在加载知识库...</p></div>
  }
  if (kbAccess.unavailable) {
    return <div className="py-24 text-center"><AlertTriangle size={30} className="mx-auto text-amber-500" /><h2 className="mt-3 text-base font-semibold text-ink-primary">内容暂不可用</h2><p className="mt-1 text-sm text-ink-muted">链接可能已失效。</p><button className="btn-secondary mt-4" onClick={() => navigate('/knowledge')}><ArrowLeft size={15} />返回知识库</button></div>
  }
  if (kbAccess.error) {
    return <div className="py-24 text-center" role="alert"><AlertTriangle size={30} className="mx-auto text-rose-500" /><h2 className="mt-3 text-base font-semibold text-ink-primary">知识库加载失败</h2><p className="mt-1 text-sm text-ink-muted">{kbAccess.error.message || '网络连接异常，请稍后重试。'}</p><button className="btn-secondary mt-4" onClick={kbAccess.retry}><RotateCcw size={15} />重新加载</button></div>
  }

  return (
    <div className="space-y-6">
      {/* 页面头部 */}
      <div className="page-header page-header-divider">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/knowledge')}
            className="btn-ghost p-1.5 rounded-lg hover:bg-cloud-200 transition-colors"
            title="返回知识库列表"
          >
            <ArrowLeft size={18} className="text-ink-muted" />
          </button>
          <div>
            <h2 className="page-title">{kbName}</h2>
            <p className="page-subtitle">文档管理 · 知识图谱（含实体浏览）</p>
          </div>
        </div>
      </div>

      {/* 当前知识库统计 */}
      <div
        className="grid grid-cols-4 gap-5"
        aria-busy={displayedDetailState.stats.status === 'loading' || displayedDetailState.stats.refreshing}
      >
        {displayedDetailState.stats.status === 'ready' ? ([
          { label: '文档总数', val: stats.documents ?? 0, color: 'text-sky-500' },
          { label: '实体总数', val: stats.entities ?? 0, color: 'text-sage-500' },
          { label: '关系总数', val: stats.relations ?? 0, color: 'text-amber-500' },
          { label: '分块总数', val: stats.chunks ?? 0, color: 'text-sky-500' },
        ].map(({ label, val, color }) => (
          <div key={label} className="stat-card">
            <p className="stat-label">{label}</p>
            <p className={`stat-value stat-value-number ${color}`}>{Number(val).toLocaleString()}</p>
          </div>
        ))) : displayedDetailState.stats.status === 'error' ? (
          <div className="stat-card col-span-4 flex items-center justify-between gap-4" role="alert">
            <div>
              <p className="stat-label">统计信息加载失败</p>
              <p className="mt-1 text-xs text-rose-600">{displayedDetailState.stats.error}</p>
            </div>
            <button className="btn-secondary text-xs" onClick={() => loadKBData({ force: true })}>
              <RotateCcw size={13} />重新加载
            </button>
          </div>
        ) : Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="stat-card">
            <div className="skeleton h-3 w-16" />
            <div className="skeleton mt-3 h-8 w-20" />
          </div>
        ))}
      </div>
      {displayedDetailState.stats.status === 'loading' && (
        <span className="sr-only" role="status" aria-live="polite">正在加载知识库统计</span>
      )}
      {displayedDetailState.stats.refreshing && (
        <p className="-mt-4 text-2xs text-ink-muted" role="status" aria-live="polite">正在刷新统计信息…</p>
      )}
      {displayedDetailState.stats.refreshError && (
        <p className="-mt-4 text-2xs text-amber-600" role="status">{displayedDetailState.stats.refreshError}</p>
      )}

      {/* 标签栏 */}
      <div className="flex items-center gap-1 p-1 rounded-xl bg-cloud-200 w-fit">
        {[
          { key: 'documents', label: '文档管理' },
          { key: 'graph', label: '知识图谱' },
          { key: 'tags', label: '标签关联' },
        ].map(tab => (
          <button key={tab.key} onClick={() => selectTab(tab.key)}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium transition-all ${
              activeTab === tab.key
                ? 'bg-white text-ink-primary shadow-cloud-sm'
                : 'text-ink-muted hover:text-ink-body'
            }`}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── 标签页：文档 ── */}
      {activeTab === 'documents' && (
      <>
        {canManageKB && <div className="card p-5">
          <UploadSection
            kbName={kbName}
            onToast={showToast}
            chunkingStrategy={chunkingStrategy}
            setChunkingStrategy={setChunkingStrategy}
            strategies={strategies}
            onUploaded={loadKBData}
            multimodal={multimodal}
            setMultimodal={setMultimodal}
            canWrite={canManageKB}
          />
        </div>}

        <section className="card p-5" aria-labelledby="vision-profile-heading">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="min-w-0 flex-1">
                <h3 id="vision-profile-heading" className="text-sm font-semibold text-ink-body">视觉向量模型</h3>
                <p className="mt-1 text-xs text-ink-muted">模型归属于当前知识库。重建期间查询继续使用旧索引，上传与多模态补处理会暂停。</p>
                {visionSettingsStatus.error && <p className="mt-2 text-xs text-amber-700" role="alert">{visionSettingsStatus.error}</p>}
              </div>
              {canManageKB ? <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-80 sm:flex-row">
                <label className="sr-only" htmlFor="kb-vision-profile">视觉向量模型</label>
                <select
                  id="kb-vision-profile"
                  className="select-field min-w-0 flex-1"
                  value={visionProfileDraft}
                  disabled={visionSettingsStatus.loading || visionSettingsStatus.saving || visionSettings?.index_state === 'reindexing'}
                  onChange={event => {
                    setVisionProfileDraft(event.target.value)
                    setVisionSettingsStatus(current => ({ ...current, confirmReindex: false, error: '' }))
                  }}
                >
                  <option value="">选择视觉向量模型</option>
                  {visionProfiles.map(profile => <option key={profile.id} value={profile.id} disabled={!profile.available}>{profile.display_name}{profile.available ? '' : '（不可用）'}</option>)}
                </select>
                <button
                  type="button"
                  className={visionSettingsStatus.confirmReindex ? 'btn-danger text-xs' : 'btn-secondary text-xs'}
                  disabled={!visionProfileDraft || (visionProfileDraft === visionSettings?.profile_id && visionSettings?.index_state !== 'failed') || visionSettingsStatus.loading || visionSettingsStatus.saving || visionSettings?.index_state === 'reindexing'}
                  onClick={saveVisionProfile}
                >
                  {visionSettingsStatus.saving ? <Loader2 size={14} className="animate-spin" /> : visionSettingsStatus.confirmReindex ? <RotateCcw size={14} /> : <Save size={14} />}
                  {visionSettingsStatus.saving ? '提交中' : visionSettingsStatus.confirmReindex ? '确认并重建' : retryFailedReindex ? '重新尝试' : '应用模型'}
                </button>
              </div> : <output className="text-sm text-ink-body">{visionSettings?.profile_id || '未配置'}</output>}
            </div>
            {visionSettings?.profile_id && <p className={`mt-3 text-2xs ${visionSettings.index_state === 'failed' ? 'text-rose-600' : 'text-ink-muted'}`} role={visionSettings.index_state === 'failed' ? 'alert' : 'status'}>当前：{visionSettings.profile_id} · {visionIndexStatus}</p>}
          </section>

        {canManageKB && (
          <div className="card p-4 flex items-start justify-between gap-4">
            <div>
              <h3 className="text-sm font-semibold text-ink-body">知识库处理维护</h3>
              <p className="text-xs text-ink-muted mt-1">
                对当前知识库中尚未完成图片、表格、公式等多模态处理的文档执行补处理。
              </p>
            </div>
            <button
              className="btn-secondary text-xs py-2 px-3 shrink-0"
              onClick={handleReprocessMultimodal}
              disabled={reprocessingMultimodal}
            >
              {reprocessingMultimodal ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
              补处理多模态
            </button>
          </div>
        )}

        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h3 className="text-sm font-semibold text-ink-body">
                文档列表{displayedDetailState.documents.status === 'ready' ? ` (${filteredDocs.length})` : ''}
              </h3>
              {displayedDetailState.documents.refreshing && (
                <span className="inline-flex items-center gap-1 text-2xs text-ink-muted" role="status" aria-live="polite">
                  <Loader2 size={11} className="animate-spin" aria-hidden="true" />正在刷新…
                </span>
              )}
              {displayedDetailState.documents.refreshError && (
                <span className="text-2xs text-amber-600" role="status">{displayedDetailState.documents.refreshError}</span>
              )}
              {canManageKB && selectedIds.size > 0 && displayedDetailState.documents.status === 'ready' && (
                <button className="btn-danger text-xs py-1.5 px-3" onClick={handleBatchDelete} disabled={batchDeleting}>
                  <Trash2 size={12} />
                  {batchDeleting ? '删除中…' : `删除选中 (${selectedIds.size})`}
                </button>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Search size={14} className="text-ink-muted"/>
              <input className="input-field text-xs w-48 py-1.5" placeholder="搜索文档…" aria-label="搜索文档" value={filter}
                onChange={e => setFilter(e.target.value)} disabled={displayedDetailState.documents.status !== 'ready'} />
            </div>
          </div>
          {documentListMode === 'loading' && (
            <span className="sr-only" role="status" aria-live="polite">正在加载文档列表</span>
          )}
          <div
            className="overflow-x-auto"
            aria-busy={documentListMode === 'loading' || displayedDetailState.documents.refreshing}
          >
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-cloud-300/60 text-left">
                  {canManageKB && <th className="pb-2.5 font-medium text-xs text-ink-muted w-8">
                    <input type="checkbox" checked={selectedIds.size > 0 && selectedIds.size === filteredDocs.length}
                      onChange={toggleSelectAll} disabled={documentListMode !== 'ready' || filteredDocs.length === 0}
                      className="w-3.5 h-3.5 accent-sky-500" />
                  </th>}
                  <th className="pb-2.5 font-medium text-xs text-ink-muted">文件名</th>
                  <th className="pb-2.5 font-medium text-xs text-ink-muted">状态</th>
                  <th className="pb-2.5 font-medium text-xs text-ink-muted">分块</th>
                  <th className="pb-2.5 font-medium text-xs text-ink-muted">字数</th>
                  <th className="pb-2.5 font-medium text-xs text-ink-muted">更新时间</th>
                  <th className="pb-2.5 font-medium text-xs text-ink-muted">操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredDocs.map(doc => {
                  const health = getDocumentHealth(doc)
                  const tagPresentation = getDocumentTagPresentation(doc)
                  const canRetry = health === 'degraded' || (health === 'failed' && doc.retryable !== false)
                  const retrying = retryingDocIds.includes(doc.id)
                  return (
                  <tr key={doc.id} className="border-b border-cloud-200 hover:bg-cloud-200/50 transition-colors">
                    {canManageKB && <td className="py-2.5">
                      <input type="checkbox" checked={selectedIds.has(doc.id)}
                        onChange={() => toggleSelect(doc.id)} className="w-3.5 h-3.5 accent-sky-500" />
                    </td>}
                    <td className="py-2.5 max-w-40 text-sm" title={doc.file}>
                      <div className="min-w-0">
                        {doc.file !== '?' ? (
                          <a href={api.downloadDocumentUrl(doc.full_id, kbName)} className="block truncate text-ink-body hover:text-sky-600 transition-colors" download>{doc.file}</a>
                        ) : (
                          <span className="block truncate text-ink-body">{doc.file}</span>
                        )}
                        <span
                          className="mt-1 inline-flex rounded-md border border-cloud-300 bg-cloud-100 px-1.5 py-0.5 text-2xs text-ink-body"
                          title={getChunkingStrategyPresentation(doc.chunking_strategy).description}
                        >
                          切块：{getChunkingStrategyPresentation(doc.chunking_strategy).name}
                        </span>
                      </div>
                    </td>
                    <td className="py-2.5">
                      <span
                        className={STATUS[health] || 'badge-info'}
                        title={health === 'degraded' ? (doc.error_message || '文本内容已可用，知识图谱正在等待补偿') : undefined}
                      >
                        {STATUS_CN[health] || health}
                        {doc.phase && PHASE_CN[doc.phase] ? <span className="ml-1 text-2xs opacity-70">({PHASE_CN[doc.phase]})</span> : null}
                      </span>
                      {health === 'degraded' && doc.failure_stage && (
                        <p className="mt-1 text-2xs text-amber-600">失败阶段：{PHASE_CN[doc.failure_stage] || doc.failure_stage}</p>
                      )}
                      {health === 'degraded' && doc.graph_status && (
                        <p className="mt-1 text-2xs text-amber-600">图谱状态：{doc.graph_status}</p>
                      )}
                      <p
                        className={`mt-1 flex items-center gap-1 text-2xs ${TAG_TONE_CLASS[tagPresentation.tone]}`}
                        title={doc.tag_error_message || tagPresentation.detail}
                      >
                        <Tag size={11} aria-hidden="true" />
                        <span>{tagPresentation.headline}</span>
                      </p>
                      {tagPresentation.densitySummary ? (
                        <p className="mt-0.5 text-2xs text-ink-400">{tagPresentation.densitySummary}</p>
                      ) : null}
                    </td>
                    <td className="py-2.5">
                      {doc.chunks > 0 ? (
                        <Link
                          className="document-chunks-link"
                          to={`/knowledge/${encodeURIComponent(kbName)}/documents/${encodeURIComponent(doc.full_id || doc.id)}/chunks`}
                          state={{ doc }}
                          title={`查看 ${doc.file} 的切块详情`}
                          aria-label={`查看 ${doc.file} 的 ${doc.chunks} 个切块`}
                        >
                          <Layers size={14} aria-hidden="true" />
                          <span className="document-chunks-link-count">{doc.chunks}</span>
                          <span>个切块</span>
                          <ArrowLeft size={13} aria-hidden="true" className="document-chunks-link-arrow" />
                        </Link>
                      ) : (
                        <span className="font-mono text-ink-muted text-sm">{doc.chunks}</span>
                      )}
                    </td>
                    <td className="py-2.5 font-mono text-ink-muted text-sm">{(doc.length || 0).toLocaleString()}</td>
                    <td className="py-2.5 text-xs text-ink-muted">{formatDate(doc.updated) || '-'}</td>
                    <td className="py-2.5 flex gap-1">
                      {doc.file !== '?' && (
                        <a href={api.downloadDocumentUrl(doc.full_id, kbName)} className="btn-ghost text-xs py-1 px-2 text-sky-600" title="下载" download><Download size={14}/></a>
                      )}
                      {canManageKB && canRetry && (
                        <button
                          className="btn-ghost text-xs py-1 px-2 text-amber-600"
                          onClick={() => handleRetryDocument(doc)}
                          disabled={retrying}
                          title={health === 'degraded' ? '补偿图谱' : '重试'}
                          aria-label={health === 'degraded' ? `补偿 ${doc.file} 的知识图谱` : `重试 ${doc.file}`}
                        >
                          {retrying ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14}/>}
                        </button>
                      )}
                      <button className="btn-ghost text-xs py-1 px-2" onClick={() => setDetailDoc(doc)} title="详情"><Eye size={14}/></button>
                      {canManageKB && (
                        <button className="btn-ghost text-xs py-1 px-2 text-rose-500" onClick={() => setDeleteConfirm(doc)} title="删除"><Trash2 size={14}/></button>
                      )}
                    </td>
                  </tr>
                  )
                })}
                {documentListMode === 'loading' && Array.from({ length: 4 }, (_, index) => (
                  <tr key={`document-skeleton-${index}`}>
                    <td colSpan={canManageKB ? 7 : 6} className="py-2">
                      <div className="skeleton h-9 w-full" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {documentListMode === 'error' && (
              <div className="py-10 text-center" role="alert">
                <AlertTriangle size={34} className="mx-auto mb-3 text-rose-500" />
                <p className="text-sm font-medium text-ink-body">文档列表加载失败</p>
                <p className="mx-auto mt-1 max-w-md text-xs text-ink-muted">{displayedDetailState.documents.error}</p>
                <button className="btn-secondary mt-4 text-xs" onClick={() => loadKBData({ force: true })}>
                  <RotateCcw size={13} />重新加载
                </button>
              </div>
            )}
            {documentListMode === 'empty' && (
              <div className="py-10 text-center">
                <FileText size={36} className="mx-auto mb-3 text-cloud-400" />
                <p className="text-sm text-ink-muted">暂无文档</p>
                <p className="text-xs text-ink-muted mt-1">上传文档或导入内容以开始构建知识库</p>
              </div>
            )}
            {documentListMode === 'no-match' && (
              <div className="py-10 text-center">
                <Search size={32} className="mx-auto mb-3 text-cloud-400" />
                <p className="text-sm text-ink-muted">没有匹配的文档</p>
                <p className="text-xs text-ink-muted mt-1">请调整搜索关键词后重试</p>
              </div>
            )}
          </div>
        </div>
      </>
      )}

      {activeTab === 'tags' && <TagRelationsPanel kbName={kbName} selectedTagId={searchParams.get('tag')} onSelectTag={selectTag} />}

      {/* ── 标签页：图谱与实体（合并）── */}
      {activeTab === 'graph' && detailState.kbName === kbName && (
        <div className="flex gap-4 h-[520px]">
          {/* 图谱面板 */}
          <div className="flex-1 card p-4 flex flex-col min-w-0">
            <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
              <div className="flex items-center gap-2">
                <Filter size={14} className="text-ink-muted" />
                <input className="input-field text-xs w-40" placeholder="搜索实体…" value={graphSearch}
                  onChange={e => { setGraphSearch(e.target.value); prevGraphFingerprint.current = '' }} />
                {graphSearch && (
                  <button className="btn-ghost p-1 text-ink-muted" onClick={() => { setGraphSearch(''); prevGraphFingerprint.current = '' }}>
                    <X size={14} />
                  </button>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <button className="btn-ghost text-xs py-1.5 px-2.5" onClick={() => handleZoom('in')} title="放大"><ZoomIn size={14}/></button>
                <button className="btn-ghost text-xs py-1.5 px-2.5" onClick={() => handleZoom('out')} title="缩小"><ZoomOut size={14}/></button>
                <button className="btn-ghost text-xs py-1.5 px-2.5" onClick={() => handleZoom('reset')} title="重置"><RotateCcw size={14}/></button>
                {/* ── 图谱编辑按钮 ── */}
                {canManageGraph && (
                  <>
                    <span className="w-px h-5 bg-cloud-300 mx-0.5" />
                    <button className="btn-primary text-xs py-1.5 px-2.5" onClick={() => setShowCreateNodeModal(true)} title="新增实体">
                      <Plus size={13}/><span className="ml-1 hidden sm:inline">新增</span>
                    </button>
                    <button className="btn-ghost text-xs py-1.5 px-2.5 text-sky-600" onClick={() => setShowCreateEdgeModal(true)} title="创建连线">
                      <Link2 size={13}/><span className="ml-1 hidden sm:inline">连线</span>
                    </button>
                  </>
                )}
                <label className="btn-ghost text-xs py-1.5 px-2.5 cursor-pointer" title="以图搜图">
                  <Image size={14} />
                  <input type="file" accept="image/*" className="hidden" ref={visionInputRef} onChange={handleImageSearch} />
                </label>
                {visionSearching && <Loader2 size={14} className="animate-spin text-sky-500" />}
              </div>
            </div>
            {visionResults && (
              <div className="p-2.5 bg-sky-50 rounded-xl border border-sky-200 space-y-1.5 mb-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-sky-700">视觉相似搜索结果 ({visionResults.count})</p>
                  <button className="btn-ghost p-0.5" onClick={() => setVisionResults(null)}><X size={14}/></button>
                </div>
                <div className="flex gap-1.5 flex-wrap">
                  {visionResults.results?.map((r, i) => (
                    <span key={i} className="bg-white rounded-md px-2 py-0.5 text-2xs text-ink-body shadow-sm">
                      {r.file || r.id} <span className="text-ink-muted">{(r.score * 100).toFixed(1)}%</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div ref={graphContainerRef} className="relative flex-1 min-h-0">
              <svg ref={svgRef} />
              {graphDataState.status === GRAPH_DATA_STATUS.LOADING && (
                <div className="absolute inset-0 p-4" role="status" aria-busy="true">
                  <div className="skeleton h-full w-full" />
                </div>
              )}
              {graphDataState.status === GRAPH_DATA_STATUS.ERROR && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center" role="alert">
                  <AlertTriangle size={34} className="text-rose-500" />
                  <p className="text-sm font-medium text-ink-body">图谱数据加载失败</p>
                  <p className="max-w-sm text-xs text-ink-muted">{graphDataState.error}</p>
                  <button className="btn-secondary mt-2 text-xs" onClick={() => void loadGraphData()}>
                    <RotateCcw size={13} />重试
                  </button>
                </div>
              )}
              {graphDataState.status === GRAPH_DATA_STATUS.READY && graph.nodes.length === 0 && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 p-4 text-center">
                  <Link2 size={34} className="mx-auto mb-1 text-cloud-400" />
                  <p className="text-sm text-ink-muted">暂无图谱数据</p>
                  <p className="text-2xs text-ink-muted">{canManageKB ? '上传文档后将自动构建知识图谱' : '当前暂无可查看的图谱内容'}</p>
                </div>
              )}
            </div>
          </div>

          {/* 实体侧栏 */}
          <div className="w-72 shrink-0 card p-4 flex flex-col overflow-hidden">
            {nodeDetails ? (
              <>
                <div className="flex items-center justify-between mb-3">
                  {renamingNode === nodeDetails.node.id ? (
                    <div className="flex items-center gap-1.5 flex-1">
                      <input
                        className="input-field text-xs flex-1 py-1"
                        value={renameValue}
                        onChange={e => setRenameValue(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') handleRenameNode(nodeDetails.node.id); if (e.key === 'Escape') setRenamingNode(null) }}
                        autoFocus
                        placeholder="新名称..."
                      />
                      <button className="btn-primary text-xs py-1 px-2" onClick={() => handleRenameNode(nodeDetails.node.id)} title="保存"><Save size={12}/></button>
                      <button className="btn-ghost text-xs py-1 px-1.5" onClick={() => setRenamingNode(null)} title="取消"><X size={12}/></button>
                    </div>
                  ) : (
                    <h3 className="text-sm font-semibold text-ink-body truncate flex-1">
                      "{nodeDetails.node.label || nodeDetails.node.id}"
                    </h3>
                  )}
                  <button
                    className="btn-ghost p-1 text-ink-muted hover:text-ink-body"
                    onClick={() => { setSelectedNode(null); setNodeDetails(null); setGraphNodeDetail(null); setRenamingNode(null) }}
                    title="返回实体列表"
                  >
                    <X size={14} />
                  </button>
                </div>

                {/* ── 节点操作 ── */}
                {canManageGraph && (
                  <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                    <button
                      className="btn-ghost text-2xs py-0.5 px-1.5 text-ink-muted hover:text-sky-600"
                      onClick={() => { setRenamingNode(nodeDetails.node.id); setRenameValue(nodeDetails.node.label || nodeDetails.node.id) }}
                      title="重命名"
                    ><Pencil size={10}/> <span className="ml-0.5">重命名</span></button>
                    <button
                      className="btn-ghost text-2xs py-0.5 px-1.5 text-ink-muted hover:text-rose-500"
                      onClick={() => setShowDeleteNodeConfirm(nodeDetails.node)}
                      title="删除实体"
                    ><Trash2 size={10}/> <span className="ml-0.5">删除</span></button>
                  </div>
                )}

                {/* ── 接口详情信息 ── */}
                {graphNodeDetail && (
                  <div className="mb-2 px-2 py-1.5 bg-sky-50/50 rounded-lg text-xs space-y-0.5">
                    <div className="flex justify-between"><span className="text-ink-muted">类型</span><span>{graphNodeDetail.entity_type || '—'}</span></div>
                    <div className="flex justify-between"><span className="text-ink-muted">来源文档</span><span>{graphNodeDetail.source_doc_count}</span></div>
                    <div className="flex justify-between"><span className="text-ink-muted">关系数</span><span>{graphNodeDetail.relation_count}</span></div>
                  </div>
                )}

                <p className="text-xs text-ink-muted mb-2">共 {nodeDetails.totalConnections} 条关系</p>
                <div className="space-y-1 flex-1 overflow-y-auto">
                  {nodeDetails.connections.map((c, i) => (
                    <div key={i} className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-cloud-100 text-xs group">
                      <span className="text-sky-500 font-mono shrink-0 text-2xs">{c.direction}</span>
                      <span className="text-ink-body truncate flex-1">{c.other}</span>
                      {c.label && <span className="text-2xs text-ink-muted shrink-0">{c.label.slice(0, 12)}</span>}
                      {canManageGraph && c._userRelationId && (
                        <button
                          className="opacity-0 group-hover:opacity-100 text-rose-400 hover:text-rose-600 shrink-0 transition-opacity"
                          onClick={() => handleDeleteEdge(c._userRelationId)}
                          title="删除此关系"
                        ><X size={10}/></button>
                      )}
                    </div>
                  ))}
                  {nodeDetails.connections.length === 0 && (
                    <p className="text-2xs text-ink-muted text-center py-4">暂无关系，可以手动创建连线</p>
                  )}
                </div>
                {nodeDetails.connectedNodes.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-cloud-200">
                    <p className="text-2xs text-ink-muted mb-1.5">关联实体</p>
                    <div className="flex flex-wrap gap-1">
                      {nodeDetails.connectedNodes.map(n => (
                        <button
                          key={n.id}
                          className="px-2 py-0.5 rounded-md text-2xs bg-cloud-100 text-ink-body hover:bg-sky-100 hover:text-sky-700 transition-colors"
                          onClick={() => {
                            const connections = graph.edges.filter(ed => _sid(ed, 'source') === n.id || _sid(ed, 'target') === n.id)
                            const connectionList = connections.map(ed => ({
                              other: _sid(ed, 'source') === n.id ? _sid(ed, 'target') : _sid(ed, 'source'),
                              label: ed.label || '', direction: _sid(ed, 'source') === n.id ? '→' : '←', _userRelationId: ed._user_relation_id || '',
                            }))
                            setSelectedNode(n)
                            setNodeDetails({
                              node: n, connections: connectionList.slice(0, 30),
                              connectedNodes: graph.nodes.filter(nd => new Set(connectionList.map(c => c.other)).has(nd.id)).slice(0, 20),
                              totalConnections: connectionList.length,
                            })
                            fetchNodeDetail(n.id)
                          }}
                        >
                          {n.label || n.id}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <>
                <h3 className="text-sm font-semibold text-ink-body mb-3">
                  全部实体 ({graphDataState.status === GRAPH_DATA_STATUS.READY ? entities.length : '—'})
                </h3>
                <div className="space-y-1 flex-1 overflow-y-auto">
                  {entities.slice(0, 200).map((e, i) => (
                    <div key={e.id || i}
                      className="px-2.5 py-1.5 rounded-lg bg-cloud-100 text-xs flex items-center justify-between hover:bg-sky-50 hover:text-sky-700 cursor-pointer transition-colors"
                      onClick={() => {
                        let node = graph.nodes.find(n => n.id === e.name)
                        if (!node) node = { id: e.name, label: e.name, degree: 0 }
                        setGraphSearch(e.name); setSelectedNode(node); prevGraphFingerprint.current = ''
                        const connections = graph.edges.filter(ed => _sid(ed, 'source') === node.id || _sid(ed, 'target') === node.id)
                        const connectionList = connections.map(ed => ({
                          other: _sid(ed, 'source') === node.id ? _sid(ed, 'target') : _sid(ed, 'source'),
                          label: ed.label || '', direction: _sid(ed, 'source') === node.id ? '→' : '←',
                        }))
                        setNodeDetails({
                          node, connections: connectionList.slice(0, 30),
                          connectedNodes: graph.nodes.filter(n => new Set(connectionList.map(c => c.other)).has(n.id)).slice(0, 20),
                          totalConnections: connectionList.length,
                        })
                        fetchNodeDetail(node.id)
                      }}>
                      <span className="text-ink-body truncate flex-1">{e.name}</span>
                      {e.type && <span className="text-2xs text-ink-muted ml-1.5 shrink-0">{e.type}</span>}
                    </div>
                  ))}
                  {graphDataState.status === GRAPH_DATA_STATUS.LOADING && (
                    <div className="space-y-1" role="status" aria-busy="true">
                      {Array.from({ length: 6 }, (_, index) => (
                        <div key={`entity-skeleton-${index}`} className="skeleton h-9 w-full rounded-lg" />
                      ))}
                    </div>
                  )}
                  {graphDataState.status === GRAPH_DATA_STATUS.ERROR && (
                    <div className="py-12 text-center" role="alert">
                      <AlertTriangle size={30} className="mx-auto mb-2 text-rose-500" />
                      <p className="text-xs font-medium text-ink-body">实体列表加载失败</p>
                      <p className="mt-1 text-2xs text-ink-muted">{graphDataState.error}</p>
                      <button className="btn-secondary mt-3 text-xs" onClick={() => void loadGraphData()}>
                        <RotateCcw size={13} />重试
                      </button>
                    </div>
                  )}
                  {graphDataState.status === GRAPH_DATA_STATUS.READY && entities.length === 0 && (
                    <div className="py-12 text-center">
                      <p className="text-xs text-ink-muted">暂无实体数据</p>
                      <p className="text-2xs text-ink-muted mt-1">上传文档后将自动抽取实体</p>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── 标签页：实体（已弃用，合并至图谱标签页）── */}

      {/* 文档详情抽屉 */}
      <AnimatePresence>
        {detailDoc && detailState.kbName === kbName && (
          <SideDrawer isOpen onRequestClose={() => setDetailDoc(null)} ariaLabel="文档详情" size="sm" className="card p-6 overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-ink-primary">文档详情</h3>
              <button className="btn-ghost p-1" onClick={() => setDetailDoc(null)} aria-label="关闭文档详情"><X size={16} aria-hidden="true"/></button>
            </div>
            <div className="space-y-3 text-sm">
              {[{ icon: FileText, label: '文件名', val: detailDoc.file },
                { icon: FileText, label: '状态', val: STATUS_CN[getDocumentHealth(detailDoc)] || getDocumentHealth(detailDoc) },
                { icon: Table, label: '图谱状态', val: detailDoc.graph_status || '-' },
                { icon: Scissors, label: '切块方式', val: getChunkingStrategyPresentation(detailDoc.chunking_strategy).name },
                { icon: FileText, label: '分块数', val: detailDoc.chunks },
                { icon: FileText, label: '字数', val: (detailDoc.length || 0).toLocaleString() },
                { icon: Clock, label: '创建时间', val: formatDate(detailDoc.created) || '-' },
                { icon: Clock, label: '更新时间', val: formatDate(detailDoc.updated) || '-' }]
                .map(({ icon: Icon, label, val }) => (
                  <div key={label} className="flex items-center gap-3">
                    <Icon size={14} className="text-ink-muted shrink-0"/>
                    <span className="text-ink-muted w-16 shrink-0">{label}</span>
                    <span className="text-ink-body truncate">{val}</span>
                  </div>
                ))}
            </div>
            {detailDoc.file !== '?' && (
              <div className="mt-4 pt-3 border-t border-cloud-200">
                <a href={api.downloadDocumentUrl(detailDoc.full_id, kbName)}
                   className="btn-primary text-sm flex items-center justify-center gap-2 w-full"
                   download>
                  <Download size={16} />
                  下载原始文件
                </a>
              </div>
            )}
          </SideDrawer>
        )}
      </AnimatePresence>

      <UserDialogConfirmation
        isOpen={Boolean(deleteConfirm && detailState.kbName === kbName)}
        title={isCancellableUploadDocument(deleteConfirm) && getDocumentHealth(deleteConfirm) === 'processing'
          ? '停止并删除上传任务'
          : (isCancellableUploadDocument(deleteConfirm) ? '删除上传任务' : '确认删除文档')}
        description={isCancellableUploadDocument(deleteConfirm) && getDocumentHealth(deleteConfirm) === 'processing'
          ? `将停止“${deleteConfirm?.file || ''}”的后台处理，并删除已生成的内容。此操作无法恢复。`
          : (isCancellableUploadDocument(deleteConfirm)
            ? `将删除“${deleteConfirm?.file || ''}”的上传任务。此操作无法恢复。`
            : `将删除“${deleteConfirm?.file || ''}”。此操作无法恢复。`)}
        icon={<Trash2 size={18} />}
        confirmLabel={deleting
          ? '删除中…'
          : (isCancellableUploadDocument(deleteConfirm) && getDocumentHealth(deleteConfirm) === 'processing'
            ? '停止并删除'
            : '确认删除')}
        cancelLabel="取消"
        danger
        confirmDisabled={deleting}
        closeDisabled={deleting}
        onConfirm={() => void handleDelete()}
        onCancel={() => setDeleteConfirm(null)}
      />

      {/* ── 创建节点弹窗 ── */}
      {showCreateNodeModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setShowCreateNodeModal(false)} role="dialog" aria-modal="true" aria-label="新增实体">
          <div className="absolute inset-0 bg-sky-900/20" />
          <div className="relative card p-6 w-96" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-ink-primary">新增实体</h3>
              <button className="btn-ghost p-1" onClick={() => setShowCreateNodeModal(false)}><X size={16}/></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-ink-muted mb-1 block">实体名称 <span className="text-rose-500">*</span></label>
                <input className="input-field text-sm w-full" placeholder="输入实体名称…" value={newNodeForm.name}
                  onChange={e => setNewNodeForm(p => ({ ...p, name: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && handleCreateNode()} autoFocus />
              </div>
              <div>
                <label className="text-xs text-ink-muted mb-1 block">类型（可选）</label>
                <select className="input-field text-sm w-full" value={newNodeForm.entity_type}
                  onChange={e => setNewNodeForm(p => ({ ...p, entity_type: e.target.value }))}>
                  <option value="">自动推断</option>
                  <option value="person">人物</option>
                  <option value="organization">组织/机构</option>
                  <option value="technology">技术/工具</option>
                  <option value="concept">概念/理论</option>
                  <option value="event">事件</option>
                  <option value="location">地点</option>
                  <option value="other">其他</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-ink-muted mb-1 block">描述（可选）</label>
                <textarea className="input-field text-sm w-full h-16 resize-none" placeholder="简短描述…" value={newNodeForm.description}
                  onChange={e => setNewNodeForm(p => ({ ...p, description: e.target.value }))} />
              </div>
            </div>
            <div className="flex gap-3 mt-4 justify-end">
              <button className="btn-secondary text-sm" onClick={() => setShowCreateNodeModal(false)}>取消</button>
              <button className="btn-primary text-sm" onClick={handleCreateNode} disabled={!newNodeForm.name.trim()}>创建</button>
            </div>
          </div>
        </div>
      )}

      {/* ── 创建边弹窗 ── */}
      {showCreateEdgeModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setShowCreateEdgeModal(false)} role="dialog" aria-modal="true" aria-label="创建连线">
          <div className="absolute inset-0 bg-sky-900/20" />
          <div className="relative card p-6 w-96" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-ink-primary">创建连线</h3>
              <button className="btn-ghost p-1" onClick={() => setShowCreateEdgeModal(false)}><X size={16}/></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-ink-muted mb-1 block">源实体 <span className="text-rose-500">*</span></label>
                <input className="input-field text-sm w-full" placeholder="实体名称…" value={newEdgeForm.source_entity}
                  onChange={e => setNewEdgeForm(p => ({ ...p, source_entity: e.target.value }))}
                  list="entity-datalist-src" autoFocus />
              </div>
              <div>
                <label className="text-xs text-ink-muted mb-1 block">目标实体 <span className="text-rose-500">*</span></label>
                <input className="input-field text-sm w-full" placeholder="实体名称…" value={newEdgeForm.target_entity}
                  onChange={e => setNewEdgeForm(p => ({ ...p, target_entity: e.target.value }))}
                  list="entity-datalist-tgt" />
              </div>
              {/* 包含全部已知实体的数据列表（自动抽取 + 用户创建） */}
              <datalist id="entity-datalist-src">
                {allEntityNames.map(name => <option key={name} value={name} />)}
              </datalist>
              <datalist id="entity-datalist-tgt">
                {allEntityNames.map(name => <option key={name} value={name} />)}
              </datalist>
              <div>
                <label className="text-xs text-ink-muted mb-1 block">关系类型</label>
                <select className="input-field text-sm w-full" value={newEdgeForm.relation_type}
                  onChange={e => setNewEdgeForm(p => ({ ...p, relation_type: e.target.value }))}>
                  <option value="related_to">关联</option>
                  <option value="requires">依赖/需要</option>
                  <option value="advances_to">进阶</option>
                  <option value="evaluates">评估</option>
                  <option value="applies_in">应用</option>
                  <option value="part_of">组成</option>
                  <option value="instance_of">实例</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-ink-muted mb-1 block">描述（可选）</label>
                <input className="input-field text-sm w-full" placeholder="关系描述…" value={newEdgeForm.description}
                  onChange={e => setNewEdgeForm(p => ({ ...p, description: e.target.value }))} />
              </div>
            </div>
            <div className="flex gap-3 mt-4 justify-end">
              <button className="btn-secondary text-sm" onClick={() => setShowCreateEdgeModal(false)}>取消</button>
              <button className="btn-primary text-sm" onClick={handleCreateEdge}
                disabled={!newEdgeForm.source_entity.trim() || !newEdgeForm.target_entity.trim()}>创建连线</button>
            </div>
          </div>
        </div>
      )}

      {/* ── 删除节点确认 ── */}
      {showDeleteNodeConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setShowDeleteNodeConfirm(null)} role="dialog" aria-modal="true" aria-label="确认删除实体">
          <div className="absolute inset-0 bg-sky-900/20" />
          <div className="relative card p-6 w-80 text-center" onClick={e => e.stopPropagation()}>
            <Trash2 size={32} className="mx-auto mb-3 text-rose-500" />
            <p className="text-ink-primary font-medium mb-1">确认删除实体</p>
            <p className="text-xs text-ink-muted mb-1 truncate">"{showDeleteNodeConfirm.label || showDeleteNodeConfirm.id}"</p>
            <p className="text-2xs text-rose-500 mb-4">删除后可从图谱中移除该实体</p>
            <div className="flex gap-3 justify-center">
              <button className="btn-secondary text-sm" onClick={() => setShowDeleteNodeConfirm(null)}>取消</button>
              <button className="btn-danger text-sm" onClick={() => handleDeleteNode(showDeleteNodeConfirm.id)}>确认删除</button>
            </div>
          </div>
        </div>
      )}

      {/* 提示消息 */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.95 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 24, scale: 0.95 }}
            role="status" aria-live="polite"
            className={`fixed bottom-6 right-6 px-5 py-3 rounded-2xl text-sm font-medium z-50 shadow-cloud-md ${
              toast.type === 'error' ? 'toast-error' : toast.type === 'success' ? 'toast-success' : 'toast-info'
            }`}>
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
