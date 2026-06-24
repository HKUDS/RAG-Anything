import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Search, Eye, Trash2, X, FileText, Clock, Filter, ZoomIn, ZoomOut, RotateCcw,
  Plus, Layers, Database, Upload, Globe, FolderOpen, ClipboardPaste,
  Loader2, CheckCircle2, XCircle, Scissors, ChevronDown, ChevronUp, Zap
} from 'lucide-react'
import * as d3 from 'd3'
import { motion, AnimatePresence } from 'framer-motion'
import { api, setCurrentKB, getCurrentKB } from '../utils/api'

const SUPPORTED = '.pdf .jpg .jpeg .png .bmp .tiff .gif .webp .doc .docx .ppt .pptx .xls .xlsx .txt .md'.split(' ')
const STATUS = { processed: 'badge-success', processing: 'badge-warning', handling: 'badge-info', failed: 'badge-error' }
const STATUS_CN = { processed: '已完成', processing: '处理中', handling: '入库中', failed: '失败' }
const PHASE_CN = { parsing: '解析文档', 'entity-extraction': '抽取实体', embedding: '向量化', 'graph-building': '构建图谱', 'multimodal-tasks': '多模态处理' }
const NODE_COLORS = ['#e8734a', '#5b9bd5', '#6b9e7a', '#d4a853', '#c9707e', '#8b5cf6', '#06b6d4', '#f97316']

const COST_COLORS = {
  free: 'text-sage-600 bg-sage-50 border-sage-200',
  medium: 'text-amber-600 bg-amber-50 border-amber-200',
  high: 'text-rose-600 bg-rose-50 border-rose-200',
}

// ====================== KB Manager Bar ======================
function KBSelector({ kbs, activeKB, onSwitch, onCreate, onDelete, deletingKB }) {
  const [showCreate, setShowCreate] = useState(false)
  const [showDelete, setShowDelete] = useState(false)
  const [newKBName, setNewKBName] = useState('')
  const inputRef = useRef()

  useEffect(() => { if (showCreate && inputRef.current) inputRef.current.focus() }, [showCreate])

  const handleCreate = () => {
    if (!newKBName.trim()) return
    onCreate(newKBName.trim())
    setNewKBName('')
    setShowCreate(false)
  }

  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2">
        <Layers size={16} className="text-warm-500" />
        <select
          className="rounded-xl border border-warm-300 bg-warm-50 text-sm text-warm-700 px-3 py-2 focus:outline-none focus:border-coral-400 transition-colors cursor-pointer min-w-[160px]"
          value={activeKB}
          onChange={e => onSwitch(e.target.value)}
        >
          {kbs.map(kb => <option key={kb.name} value={kb.name}>{kb.label}</option>)}
        </select>
      </div>

      <button onClick={() => setShowCreate(!showCreate)} className="btn-secondary text-xs py-2">
        <Plus size={14} /> 新建知识库
      </button>

      {activeKB !== 'default' && (
        <button onClick={() => setShowDelete(true)} className="btn-ghost text-xs py-2 text-rose-500 hover:text-rose-600 hover:bg-rose-50">
          <Trash2 size={14} /> 删除
        </button>
      )}

      {/* Create popover */}
      <AnimatePresence>
        {showCreate && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.95 }}
            className="absolute top-full left-0 mt-2 w-72 card p-4 shadow-warm-md z-50"
          >
            <p className="text-sm font-medium text-warm-800 mb-3">新建知识库</p>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-warm-500 mb-1 block">名称</label>
                <input
                  ref={inputRef}
                  className="input-field text-sm"
                  placeholder="输入知识库名称…"
                  value={newKBName}
                  onChange={e => setNewKBName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleCreate(); if (e.key === 'Escape') setShowCreate(false) }}
                />
              </div>
              <div className="flex gap-2">
                <button className="btn-primary text-xs flex-1" onClick={handleCreate}>创建</button>
                <button className="btn-secondary text-xs" onClick={() => setShowCreate(false)}>取消</button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Delete confirm */}
      <AnimatePresence>
        {showDelete && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-warm-900/20"
            onClick={() => setShowDelete(false)}
          >
            <div className="card p-6 max-w-sm w-full m-4" onClick={e => e.stopPropagation()}>
              <Trash2 size={32} className="mx-auto mb-3 text-rose-500" />
              <p className="text-warm-800 font-medium text-center mb-1">确认删除知识库</p>
              <p className="text-sm text-warm-500 text-center mb-2">
                「{activeKB}」
              </p>
              <p className="text-xs text-rose-500 text-center mb-4">将清除所有文档、实体和向量数据，不可恢复</p>
              <div className="flex gap-3 justify-center">
                <button className="btn-secondary text-sm" onClick={() => setShowDelete(false)}>取消</button>
                <button
                  className="btn-danger text-sm"
                  disabled={deletingKB}
                  onClick={() => onDelete(activeKB, () => setShowDelete(false))}
                >
                  {deletingKB ? '删除中…' : '确认删除'}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ====================== Upload Section ======================
function UploadSection({ onToast, chunkingStrategy, setChunkingStrategy, strategies, onUploaded,
  multimodal, setMultimodal }) {
  const [dragOver, setDragOver] = useState(false)
  const [files, setFiles] = useState([])
  const [urlInput, setUrlInput] = useState('')
  const [urlLoading, setUrlLoading] = useState(false)
  const [pasteContent, setPasteContent] = useState('')
  const [pasteTitle, setPasteTitle] = useState('')
  const [folderPath, setFolderPath] = useState('')
  const [folderLoading, setFolderLoading] = useState(false)
  const [showUpload, setShowUpload] = useState(false)

  const addFile = useCallback((file) => {
    setFiles(prev => [...prev, { name: file.name, size: file.size, file, status: 'pending' }])
  }, [])

  const processFile = async (idx) => {
    setFiles(prev => prev.map((f, i) => i === idx ? { ...f, status: 'uploading' } : f))
    try {
      await api.uploadFile(files[idx].file, chunkingStrategy, multimodal)
      setFiles(prev => prev.map((f, i) => i === idx ? { ...f, status: 'done' } : f))
      onToast?.(`${files[idx].name} 上传成功 ✨`, 'success')
      onUploaded?.()
    } catch (e) {
      setFiles(prev => prev.map((f, i) => i === idx ? { ...f, status: 'error', error: e.message } : f))
      onToast?.(`${files[idx].name} 失败: ${e.message}`, 'error')
    }
  }

  const processAllFiles = async () => {
    const pending = files.map((f, i) => ({ ...f, idx: i })).filter(f => f.status === 'pending')
    if (pending.length === 0) return
    setFiles(prev => prev.map(f => f.status === 'pending' ? { ...f, status: 'uploading' } : f))
    let ok = 0, fail = 0
    for (const { idx } of pending) {
      try {
        await api.uploadFile(files[idx].file, chunkingStrategy, multimodal)
        setFiles(prev => prev.map((x, i) => i === idx ? { ...x, status: 'done' } : x))
        ok++
      } catch (e) {
        setFiles(prev => prev.map((x, i) => i === idx ? { ...x, status: 'error', error: e.message } : x))
        fail++
      }
    }
    onToast?.(`批量上传: ${ok} 成功, ${fail} 失败`, fail > 0 ? 'error' : 'success')
    if (ok > 0) onUploaded?.()
  }

  const handleDrop = useCallback((e) => {
    e.preventDefault(); setDragOver(false)
    Array.from(e.dataTransfer.files).forEach(addFile)
  }, [addFile])

  const handlePaste = async () => {
    if (!pasteContent.trim()) return
    try {
      await api.uploadContent(pasteContent, pasteTitle || '粘贴内容', chunkingStrategy, multimodal)
      onToast?.('内容已入库 📝', 'success')
      setPasteContent(''); setPasteTitle('')
      onUploaded?.()
    } catch (e) { onToast?.(e.message, 'error') }
  }

  const handleUrlImport = async () => {
    if (!urlInput.trim()) return
    setUrlLoading(true)
    try {
      const params = new URLSearchParams({ url: urlInput })
      if (chunkingStrategy) params.set('chunking_strategy', chunkingStrategy)
      if (multimodal.enable_image !== undefined) params.set('enable_image', multimodal.enable_image)
      if (multimodal.enable_table !== undefined) params.set('enable_table', multimodal.enable_table)
      if (multimodal.enable_equation !== undefined) params.set('enable_equation', multimodal.enable_equation)
      if (multimodal.enable_video !== undefined) params.set('enable_video', multimodal.enable_video)
      const res = await fetch(`/api/upload/url?${params.toString()}`, { method: 'POST' })
      if (!res.ok) throw new Error((await res.json()).detail || '导入失败')
      onToast?.('URL 导入成功 🌐', 'success')
      setUrlInput('')
      onUploaded?.()
    } catch (e) { onToast?.(`URL 导入失败: ${e.message}`, 'error') }
    setUrlLoading(false)
  }

  const handleFolderUpload = async () => {
    if (!folderPath.trim()) return
    setFolderLoading(true)
    try {
      await api.uploadFolder(folderPath, chunkingStrategy, multimodal)
      onToast?.('文件夹处理完成 📂', 'success')
      onUploaded?.()
    } catch (e) { onToast?.(`处理失败: ${e.message}`, 'error') }
    setFolderLoading(false)
  }

  return (
    <div className="space-y-4">
      <button
        onClick={() => setShowUpload(!showUpload)}
        className="flex items-center gap-2 text-sm font-medium text-warm-600 hover:text-coral-500 transition-colors"
      >
        {showUpload ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        <Upload size={16} />
        上传文档到当前知识库
        {files.length > 0 && <span className="text-xs text-warm-500">({files.length} 个文件)</span>}
      </button>

      <AnimatePresence>
        {showUpload && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden space-y-4"
          >
            {/* Drag & Drop */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              className={`card border-dashed p-8 text-center cursor-pointer transition-all ${
                dragOver ? 'border-coral-400 bg-coral-50/50 scale-[1.01] shadow-warm-md' : 'border-warm-300/70'
              }`}
              onClick={() => document.getElementById('kb-file-input').click()}
            >
              <input id="kb-file-input" type="file" multiple className="hidden"
                onChange={(e) => Array.from(e.target.files).forEach(addFile)} />
              <Upload size={36} className="mx-auto mb-3 text-warm-500" />
              <p className="text-warm-700 font-medium text-sm">拖拽文件到此处，或点击选择</p>
              <p className="text-warm-500 text-xs mt-1">PDF · Word · PPT · Excel · 图片 · 文本 · 视频</p>
            </div>

            {/* Chunking Strategy */}
            <div className="flex gap-2 flex-wrap items-center">
              <span className="text-xs text-warm-500 flex items-center gap-1"><Scissors size={12}/> 分块策略:</span>
              {Object.entries(strategies).length > 0 ? (
                Object.entries(strategies).map(([key, meta]) => {
                  const isActive = (chunkingStrategy || 'recursive') === key
                  return (
                    <button key={key}
                      onClick={() => setChunkingStrategy(key)}
                      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs border transition-all ${
                        isActive
                          ? 'border-coral-300 bg-coral-50 text-coral-600'
                          : 'border-warm-200 text-warm-500 hover:border-warm-300'
                      }`}>
                      {meta.name}
                      <span className={`text-[9px] px-1 py-0.5 rounded-full border ${COST_COLORS[meta.cost_level] || COST_COLORS.free}`}>
                        {meta.cost}
                      </span>
                    </button>
                  )
                })
              ) : (
                <span className="text-xs text-warm-500">加载中...</span>
              )}
            </div>

            {/* Multimodal Toggles */}
            <div className="flex gap-2 flex-wrap items-center">
              <span className="text-xs text-warm-500 flex items-center gap-1"><Zap size={12}/> 多模态处理:</span>
              {[
                { key: 'enable_image', label: '图片', desc: 'VLM 分析图片' },
                { key: 'enable_table', label: '表格', desc: '提取表格数据' },
                { key: 'enable_equation', label: '公式', desc: 'LaTeX 转换' },
                { key: 'enable_video', label: '视频', desc: '提取帧+音频' },
              ].map(({ key, label, desc }) => (
                <button key={key}
                  onClick={() => setMultimodal(prev => ({ ...prev, [key]: !prev[key] }))}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs border transition-all ${
                    multimodal[key]
                      ? 'border-coral-300 bg-coral-50 text-coral-600'
                      : 'border-warm-200 text-warm-400 hover:border-warm-300'
                  }`}
                  title={desc}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* URL / Folder / Paste */}
            <div className="grid grid-cols-3 gap-4">
              <div className="card p-3 space-y-2">
                <p className="text-xs font-medium text-warm-600 flex items-center gap-1"><Globe size={12}/> URL 导入</p>
                <input className="input-field text-xs py-1.5" placeholder="https://..." value={urlInput}
                  onChange={e => setUrlInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleUrlImport()} />
                <button className="btn-primary text-xs w-full py-1.5" onClick={handleUrlImport} disabled={!urlInput || urlLoading}>
                  {urlLoading ? '导入中…' : '导入'}
                </button>
              </div>
              <div className="card p-3 space-y-2">
                <p className="text-xs font-medium text-warm-600 flex items-center gap-1"><FolderOpen size={12}/> 文件夹</p>
                <input className="input-field text-xs py-1.5" placeholder="D:\文档" value={folderPath}
                  onChange={e => setFolderPath(e.target.value)} />
                <button className="btn-primary text-xs w-full py-1.5" onClick={handleFolderUpload} disabled={!folderPath || folderLoading}>
                  {folderLoading ? '处理中…' : '处理'}
                </button>
              </div>
              <div className="card p-3 space-y-2">
                <p className="text-xs font-medium text-warm-600 flex items-center gap-1"><ClipboardPaste size={12}/> 粘贴</p>
                <input className="input-field text-xs py-1.5" placeholder="标题" value={pasteTitle}
                  onChange={e => setPasteTitle(e.target.value)} />
                <textarea className="input-field text-xs h-16 resize-none" placeholder="内容…" value={pasteContent}
                  onChange={e => setPasteContent(e.target.value)} />
                <button className="btn-primary text-xs w-full py-1.5" onClick={handlePaste} disabled={!pasteContent.trim()}>提交</button>
              </div>
            </div>

            {/* File list */}
            {files.length > 0 && (
              <div className="card p-3 space-y-1.5">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-warm-600">文件列表 ({files.length})</p>
                  {files.some(f => f.status === 'pending') && (
                    <button className="btn-primary text-xs py-1 px-3" onClick={processAllFiles}>
                      全部上传 ({files.filter(f => f.status === 'pending').length})
                    </button>
                  )}
                </div>
                {files.map((f, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-1.5 bg-warm-50 rounded-lg text-xs">
                    <div className="flex items-center gap-2">
                      {f.status === 'uploading' ? <Loader2 size={14} className="animate-spin text-coral-500" />
                        : f.status === 'done' ? <CheckCircle2 size={14} className="text-sage-500" />
                        : f.status === 'error' ? <XCircle size={14} className="text-rose-500" />
                        : <FileText size={14} className="text-warm-500" />}
                      <span className="text-warm-700 truncate max-w-[200px]">{f.name}</span>
                      {f.error && <span className="text-rose-500">{f.error}</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-warm-500 font-mono">{(f.size / 1024).toFixed(0)} KB</span>
                      {f.status === 'pending' && <button className="btn-primary text-xs py-0.5 px-2" onClick={() => processFile(i)}>上传</button>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ====================== MAIN PAGE ======================
export default function KnowledgePage() {
  const [kbs, setKBs] = useState([])
  const [activeKB, setActiveKB] = useState(null)
  const [kbsLoaded, setKbsLoaded] = useState(false)
  const [docs, setDocs] = useState([])
  const [entities, setEntities] = useState([])
  const [stats, setStats] = useState({})
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [filter, setFilter] = useState('')
  const [graphSearch, setGraphSearch] = useState('')
  const [detailDoc, setDetailDoc] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [selectedNode, setSelectedNode] = useState(null)
  const [nodeDetails, setNodeDetails] = useState(null)
  const [deletingKB, setDeletingKB] = useState(false)
  const [toast, setToast] = useState(null)
  const [chunkingStrategy, setChunkingStrategy] = useState('')
  const [strategies, setStrategies] = useState({})
  const [multimodal, setMultimodal] = useState({
    enable_image: true, enable_table: true, enable_equation: true, enable_video: false
  })
  const svgRef = useRef()
  const graphContainerRef = useRef()
  const zoomRef = useRef(null)
  const prevGraphFingerprint = useRef('')
  const prevGraphSearch = useRef('')

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  // Load KB list
  const loadKBs = useCallback(async () => {
    const r = await api.listKBs().catch(() => null)
    if (r) {
      const kbList = r.knowledge_bases || []
      setKBs(kbList)
      const current = getCurrentKB()
      if (current && kbList.some(kb => kb.name === current)) {
        setActiveKB(current)
        // currentKB 模块变量已正确，无需更新
      } else if (r.active && kbList.some(kb => kb.name === r.active)) {
        // 仅当服务端 active_kb 属于当前用户时才使用
        setActiveKB(r.active)
        setCurrentKB(r.active)
      } else if (kbList.length > 0) {
        // 回退到用户自己的第一个 KB
        setActiveKB(kbList[0].name)
        setCurrentKB(kbList[0].name)
      }
      // 如果没有可用的 active KB，保持 null，不设无效默认值
    }
    setKbsLoaded(true)
  }, [])

  // Load data for selected KB
  const loadKBData = useCallback(() => {
    api.getDocuments().then(r => setDocs(r.documents || [])).catch(() => {})
    api.getStats().then(setStats).catch(() => {})
    api.getEntities(200).then(r => setEntities(r.entities || [])).catch(() => {})
    api.getGraph().then(r => {
      const degree = {}
      ;(r.edges || []).forEach(e => {
        degree[e.source] = (degree[e.source] || 0) + 1
        degree[e.target] = (degree[e.target] || 0) + 1
      })
      const nodes = (r.nodes || []).map(n => ({ ...n, degree: degree[n.id] || 0 }))
      nodes.sort((a, b) => b.degree - a.degree)
      setGraph({ nodes, edges: r.edges || [] })
    }).catch(() => {})
  }, [])

  // Load strategies
  useEffect(() => {
    api.getSettings().then(s => {
      if (s.chunking_strategies) setStrategies(s.chunking_strategies)
      if (s.chunking_strategy) setChunkingStrategy(s.chunking_strategy)
    }).catch(() => {})
  }, [])

  // Init
  useEffect(() => { loadKBs() }, [loadKBs])
  useEffect(() => {
    if (!kbsLoaded || !activeKB) return
    loadKBData()
    const t = setInterval(loadKBData, 8000)
    return () => clearInterval(t)
  }, [activeKB, kbsLoaded, loadKBData])

  // Switch KB
  const switchKB = async (name) => {
    await api.switchKB(name)
    setCurrentKB(name)
    setActiveKB(name)
    setSelectedIds(new Set())
    loadKBs()
  }

  // Create KB
  const createKB = async (name) => {
    try {
      await api.createKB(name, name)
      showToast(`知识库「${name}」已创建 ✨`, 'success')
      loadKBs()
    } catch (e) {
      showToast('创建失败: ' + e.message, 'error')
    }
  }

  // Delete KB
  const deleteKB = async (name, onDone) => {
    setDeletingKB(true)
    try {
      await api.deleteKB(name)
      showToast(`知识库「${name}」已删除`, 'success')
      onDone?.()
      // loadKBs() 会从服务端获取正确的 active KB，无需硬编码 'default'
      await loadKBs()
    } catch (e) {
      showToast('删除失败: ' + e.message, 'error')
    } finally {
      setDeletingKB(false)
    }
  }

  // D3 Graph
  const drawGraph = useCallback(() => {
    if (!svgRef.current || !graph.nodes.length) return

    // Skip redraw if graph data hasn't changed (prevents 8s polling from resetting zoom/simulation)
    const fingerprint = JSON.stringify({
      ns: graph.nodes.map(n => n.id).sort().join(','),
      es: graph.edges.map(e => `${e.source}|${e.target}|${e.label || ''}`).sort().join(';'),
      q: graphSearch.trim(),
      sn: selectedNode?.id || '',
    })
    if (fingerprint === prevGraphFingerprint.current && graphSearch.trim() === prevGraphSearch.current) {
      return
    }
    prevGraphFingerprint.current = fingerprint
    prevGraphSearch.current = graphSearch.trim()

    try {
      const svg = d3.select(svgRef.current)

      // Save current zoom transform before clearing SVG
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
        displayNodes = displayNodes.slice(0, 60)
      }
      const displayIds = new Set(displayNodes.map(n => n.id))
      const displayEdges = graph.edges.filter(e => displayIds.has(e.source) && displayIds.has(e.target))

      const W = graphContainerRef.current?.clientWidth || 600
      const H = 420
      const svgEl = svg.attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%').attr('height', H)
      const g = svgEl.append('g')
      const zoom = d3.zoom().scaleExtent([0.3, 4]).on('zoom', (e) => g.attr('transform', e.transform))
      svgEl.call(zoom)
      // Restore saved zoom/pan position so graph doesn't jump on data update
      svgEl.call(zoom.transform, savedTransform)
      zoomRef.current = zoom

      const colorScale = d3.scaleOrdinal(NODE_COLORS)
      const sizeScale = d3.scaleSqrt().domain([0, d3.max(displayNodes, d => d.degree) || 1]).range([5, 18])

      const sim = d3.forceSimulation(displayNodes)
        .force('link', d3.forceLink(displayEdges).id(d => d.id).distance(d => 80 / Math.sqrt((d.source.degree || 1) + 1)))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(W / 2, H / 2))
        .force('collision', d3.forceCollide().radius(d => sizeScale(d.degree) + 8))

      const link = g.append('g').selectAll('line').data(displayEdges).join('line')
        .attr('stroke', '#d9cebc').attr('stroke-width', 0.5).attr('stroke-opacity', 0.6)
      const edgeLabels = g.append('g').selectAll('text').data(displayEdges.slice(0, 15)).join('text')
        .text(d => (d.label || '').slice(0, 10)).attr('font-size', 7).attr('fill', '#8a8276').attr('text-anchor', 'middle')

      const nodeGroup = g.append('g').selectAll('g').data(displayNodes).join('g').attr('cursor', 'pointer')
        .call(d3.drag().on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
          .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
          .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null }))

      nodeGroup.append('circle').attr('r', d => sizeScale(d.degree)).attr('fill', d => colorScale(d.id))
        .attr('stroke', '#f3efe6').attr('stroke-width', 1).attr('opacity', 0.85)
      nodeGroup.filter(d => d.degree >= 2 || displayNodes.length <= 20).append('text')
        .text(d => (d.label || d.id || '').slice(0, 10))
        .attr('font-size', d => Math.max(7, Math.min(11, sizeScale(d.degree) * 0.7)))
        .attr('fill', '#4a433b').attr('text-anchor', 'middle').attr('dy', d => sizeScale(d.degree) + 12)
        .attr('font-family', "'Microsoft YaHei', 'SimHei', sans-serif")

      nodeGroup.on('click', async (e, d) => {
        e.stopPropagation(); setSelectedNode(d)
        const connections = graph.edges.filter(e => e.source === d.id || e.target === d.id)
        const connectedNames = new Set(); const connectionList = []
        connections.forEach(e => {
          const other = e.source === d.id ? e.target : e.source
          connectedNames.add(other)
          connectionList.push({ other, label: e.label || '', direction: e.source === d.id ? '→' : '←' })
        })
        setNodeDetails({
          node: d, connections: connectionList.slice(0, 30),
          connectedNodes: graph.nodes.filter(n => connectedNames.has(n.id)).slice(0, 20),
          totalConnections: connectionList.length,
        })
      })
      svgEl.on('click', () => { setSelectedNode(null); setNodeDetails(null) })

      if (selectedNode) {
        nodeGroup.select('circle').attr('opacity', d => d.id === selectedNode.id ? 1 : 0.3)
        link.attr('stroke-opacity', d => d.source.id === selectedNode.id || d.target.id === selectedNode.id ? 0.9 : 0.15)
      }
      sim.on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y)
        edgeLabels.attr('x', d => (d.source.x + d.target.x) / 2).attr('y', d => (d.source.y + d.target.y) / 2)
        nodeGroup.attr('transform', d => `translate(${d.x},${d.y})`)
      })
      return () => sim.stop()
    } catch(e) { console.warn('D3 error:', e) }
  }, [graph, graphSearch, selectedNode])

  useEffect(() => { return drawGraph() }, [drawGraph])

  const handleZoom = (dir) => {
    if (!svgRef.current) return
    const svg = d3.select(svgRef.current)
    if (dir === 'in') svg.transition().call(zoomRef.current.scaleBy, 1.5)
    else if (dir === 'out') svg.transition().call(zoomRef.current.scaleBy, 0.7)
    else svg.transition().call(zoomRef.current.transform, d3.zoomIdentity)
  }

  const filteredDocs = docs.filter(d => d.file?.toLowerCase().includes(filter.toLowerCase()))

  const handleDelete = async () => {
    if (!deleteConfirm) return
    setDeleting(true)
    try { await api.deleteDocument(deleteConfirm.id); setDeleteConfirm(null); loadKBData() }
    catch(e) { showToast('删除失败: ' + e.message, 'error') }
    setDeleting(false)
  }

  const toggleSelect = (id) => {
    setSelectedIds(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next })
  }
  const toggleSelectAll = () => {
    setSelectedIds(prev => prev.size === filteredDocs.length ? new Set() : new Set(filteredDocs.map(d => d.id)))
  }

  const handleBatchDelete = async () => {
    setBatchDeleting(true)
    try {
      const res = await api.deleteDocuments([...selectedIds])
      setSelectedIds(new Set()); loadKBData()
      showToast(`已删除 ${res.total_deleted} 个文档`, 'success')
    } catch(e) { showToast('批量删除失败: ' + e.message, 'error') }
    setBatchDeleting(false)
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header page-header-divider">
        <div>
          <h2 className="page-title">📚 知识库管理</h2>
          <p className="page-subtitle">管理知识库、上传文档、查看图谱</p>
        </div>
      </div>

      {/* KB Selector + Create */}
      <div className="relative">
        <KBSelector
          kbs={kbs}
          activeKB={activeKB}
          onSwitch={switchKB}
          onCreate={createKB}
          onDelete={deleteKB}
          deletingKB={deletingKB}
        />
      </div>

      {/* Stats for active KB */}
      <div className="grid grid-cols-4 gap-5">
        {[
          { label: '文档总数', val: stats.documents || 0, color: 'text-coral-500' },
          { label: '实体总数', val: stats.entities || 0, color: 'text-sage-500' },
          { label: '关系总数', val: stats.relations || 0, color: 'text-amber-500' },
          { label: '分块总数', val: stats.chunks || 0, color: 'text-sky-500' },
        ].map(({ label, val, color }) => (
          <div key={label} className="stat-card">
            <p className="stat-label">{label}</p>
            <p className={`stat-value ${color}`}>{val.toLocaleString()}</p>
          </div>
        ))}
      </div>

      {/* Upload Section */}
      <div className="card p-5">
        <UploadSection
          onToast={showToast}
          chunkingStrategy={chunkingStrategy}
          setChunkingStrategy={setChunkingStrategy}
          strategies={strategies}
          onUploaded={loadKBData}
          multimodal={multimodal}
          setMultimodal={setMultimodal}
        />
      </div>

      {/* Document Table */}
      <div className="card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-semibold text-warm-700">文档列表 ({filteredDocs.length})</h3>
            {selectedIds.size > 0 && (
              <button
                className="btn-danger text-xs py-1.5 px-3"
                onClick={handleBatchDelete} disabled={batchDeleting}
              >
                <Trash2 size={12} />
                {batchDeleting ? '删除中…' : `删除选中 (${selectedIds.size})`}
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Search size={14} className="text-warm-500"/>
            <input className="input-field text-xs w-48 py-1.5" placeholder="搜索文档…" value={filter}
              onChange={e => setFilter(e.target.value)} />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-warm-200/60 text-left">
                <th className="pb-2.5 font-medium text-xs text-warm-500 w-8">
                  <input type="checkbox" checked={selectedIds.size > 0 && selectedIds.size === filteredDocs.length}
                    onChange={toggleSelectAll} className="w-3.5 h-3.5 accent-coral-500" />
                </th>
                <th className="pb-2.5 font-medium text-xs text-warm-500">文件名</th>
                <th className="pb-2.5 font-medium text-xs text-warm-500">状态</th>
                <th className="pb-2.5 font-medium text-xs text-warm-500">分块</th>
                <th className="pb-2.5 font-medium text-xs text-warm-500">字数</th>
                <th className="pb-2.5 font-medium text-xs text-warm-500">更新时间</th>
                <th className="pb-2.5 font-medium text-xs text-warm-500">操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredDocs.map(doc => (
                <tr key={doc.id} className="border-b border-warm-100 hover:bg-warm-50/50 transition-colors">
                  <td className="py-2.5">
                    <input type="checkbox" checked={selectedIds.has(doc.id)}
                      onChange={() => toggleSelect(doc.id)} className="w-3.5 h-3.5 accent-coral-500" />
                  </td>
                  <td className="py-2.5 text-warm-700 max-w-40 truncate text-sm" title={doc.file}>{doc.file}</td>
                  <td className="py-2.5">
                    <span className={STATUS[doc.status] || 'badge-info'}>
                      {STATUS_CN[doc.status] || doc.status}
                      {doc.phase && PHASE_CN[doc.phase] ? <span className="ml-1 text-[10px] opacity-70">({PHASE_CN[doc.phase]})</span> : null}
                    </span>
                  </td>
                  <td className="py-2.5 font-mono text-warm-500 text-sm">{doc.chunks}</td>
                  <td className="py-2.5 font-mono text-warm-500 text-sm">{(doc.length || 0).toLocaleString()}</td>
                  <td className="py-2.5 text-xs text-warm-500">{doc.updated?.slice(0, 16) || '-'}</td>
                  <td className="py-2.5 flex gap-1">
                    {doc.status === 'failed' && (
                      <button className="btn-ghost text-xs py-1 px-2 text-amber-600" onClick={async () => { await api.retryDocument(doc.id); loadKBData() }} title="重试"><RotateCcw size={14}/></button>
                    )}
                    <button className="btn-ghost text-xs py-1 px-2" onClick={() => setDetailDoc(doc)} title="详情"><Eye size={14}/></button>
                    <button className="btn-ghost text-xs py-1 px-2 text-rose-500" onClick={() => setDeleteConfirm(doc)} title="删除"><Trash2 size={14}/></button>
                  </td>
                </tr>
              ))}
              {filteredDocs.length === 0 && (
                <tr><td colSpan={7} className="py-12 text-center">
                  <div className="empty-state py-8">
                    <div className="empty-state-icon">📄</div>
                    <p className="empty-state-title">这里还没有文档</p>
                    <p className="empty-state-desc">在上方展开上传区域，添加第一个文档</p>
                  </div>
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Knowledge Graph + Entity Detail Row */}
      <div className="grid grid-cols-2 gap-5">
        {/* Graph */}
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-warm-700 flex items-center gap-2">
              <Filter size={14}/>知识图谱
              <span className="text-[10px] text-warm-500 font-normal">
                {graph.nodes.length} 节点 · {graph.edges.length} 边
              </span>
            </h3>
            <div className="flex items-center gap-1.5">
              <input className="input-field text-xs w-32 py-1.5" placeholder="搜索实体…" value={graphSearch}
                onChange={e => setGraphSearch(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && drawGraph()} />
              <button className="btn-ghost p-1.5" onClick={() => handleZoom('in')} title="放大"><ZoomIn size={14}/></button>
              <button className="btn-ghost p-1.5" onClick={() => handleZoom('out')} title="缩小"><ZoomOut size={14}/></button>
              <button className="btn-ghost p-1.5" onClick={() => handleZoom('reset')} title="重置"><RotateCcw size={14}/></button>
            </div>
          </div>
          <div ref={graphContainerRef} className="relative">
            <svg ref={svgRef} className="w-full bg-warm-50/50 rounded-xl cursor-grab active:cursor-grabbing" style={{ minHeight: 420 }} />
            {selectedNode && (
              <div className="absolute top-2 left-2 bg-white/95 border border-warm-200 rounded-xl p-2 text-xs max-w-48 shadow-warm-md">
                <p className="text-warm-700 font-medium truncate">{selectedNode.label || selectedNode.id}</p>
                <p className="text-warm-500">关联: {selectedNode.degree} 条边</p>
                <p className="text-[10px] text-warm-500 mt-1">点击空白取消选中</p>
              </div>
            )}
          </div>
        </div>

        {/* Entity detail / list */}
        <div className="card p-4 space-y-3">
          {nodeDetails ? (
            <>
              <h3 className="text-sm font-semibold text-warm-700">🔗 "{nodeDetails.node.label || nodeDetails.node.id}" 的关联</h3>
              <div className="space-y-2 max-h-[420px] overflow-y-auto">
                <p className="text-xs text-warm-500">共 {nodeDetails.totalConnections} 条关系</p>
                {nodeDetails.connections.map((c, i) => (
                  <div key={i} className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-warm-50 text-xs">
                    <span className="text-coral-500 font-mono shrink-0">{c.direction}</span>
                    <span className="text-warm-600 truncate flex-1">{c.other}</span>
                    {c.label && <span className="text-[10px] text-warm-500 shrink-0">{c.label.slice(0, 15)}</span>}
                  </div>
                ))}
                {nodeDetails.connectedNodes.length > 0 && (
                  <div className="mt-3">
                    <p className="text-[10px] text-warm-500 mb-1">关联实体:</p>
                    <div className="flex flex-wrap gap-1">
                      {nodeDetails.connectedNodes.map(n => (
                        <span key={n.id} className="px-2 py-0.5 rounded-lg text-[10px] bg-warm-100 text-warm-600">{n.label || n.id}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <>
              <h3 className="text-sm font-semibold text-warm-700">全部实体 ({entities.length})</h3>
              <div className="space-y-1 max-h-[420px] overflow-y-auto">
                {entities.slice(0, 100).map((e, i) => (
                  <div key={e.id || i}
                    className="px-3 py-1.5 rounded-xl bg-warm-50 text-xs flex items-center justify-between hover:bg-warm-100 cursor-pointer transition-colors"
                    onClick={() => {
                      let node = graph.nodes.find(n => n.id === e.name)
                      if (!node) node = { id: e.name, label: e.name, degree: 0 }
                      setGraphSearch(e.name); setSelectedNode(node)
                      const connections = graph.edges.filter(ed => ed.source === node.id || ed.target === node.id)
                      const connectionList = connections.map(ed => ({
                        other: ed.source === node.id ? ed.target : ed.source,
                        label: ed.label || '', direction: ed.source === node.id ? '→' : '←',
                      }))
                      setNodeDetails({
                        node, connections: connectionList.slice(0, 30),
                        connectedNodes: graph.nodes.filter(n => new Set(connectionList.map(c => c.other)).has(n.id)).slice(0, 20),
                        totalConnections: connectionList.length,
                      })
                    }}>
                    <span className="text-warm-700 truncate flex-1">{e.name}</span>
                    {e.type && <span className="text-[10px] text-warm-500 ml-2">{e.type}</span>}
                  </div>
                ))}
                {entities.length === 0 && (
                  <div className="py-8 text-center">
                    <p className="text-xs text-warm-500">暂无实体数据</p>
                    <p className="text-[10px] text-warm-500 mt-1">上传文档后将自动抽取实体 🏷️</p>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Doc Detail Drawer */}
      {detailDoc && (
        <div className="fixed inset-0 z-50 flex justify-end" onClick={() => setDetailDoc(null)}>
          <div className="absolute inset-0 bg-warm-900/20" />
          <div className="relative w-96 card m-3 p-6 overflow-y-auto animate-slide-in-right" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-warm-800">文档详情</h3>
              <button className="btn-ghost p-1" onClick={() => setDetailDoc(null)}><X size={16}/></button>
            </div>
            <div className="space-y-3 text-sm">
              {[{ icon: FileText, label: '文件名', val: detailDoc.file },
                { icon: FileText, label: '状态', val: STATUS_CN[detailDoc.status] || detailDoc.status },
                { icon: FileText, label: '分块数', val: detailDoc.chunks },
                { icon: FileText, label: '字数', val: (detailDoc.length || 0).toLocaleString() },
                { icon: Clock, label: '创建时间', val: detailDoc.created?.slice(0, 19) || '-' },
                { icon: Clock, label: '更新时间', val: detailDoc.updated?.slice(0, 19) || '-' }]
                .map(({ icon: Icon, label, val }) => (
                  <div key={label} className="flex items-center gap-3">
                    <Icon size={14} className="text-warm-500 shrink-0"/>
                    <span className="text-warm-500 w-16 shrink-0">{label}</span>
                    <span className="text-warm-700 truncate">{val}</span>
                  </div>
                ))}
            </div>
          </div>
        </div>
      )}

      {/* Document Delete Confirm */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setDeleteConfirm(null)}>
          <div className="absolute inset-0 bg-warm-900/20" />
          <div className="relative card p-6 w-80 text-center" onClick={e => e.stopPropagation()}>
            <Trash2 size={32} className="mx-auto mb-3 text-rose-500" />
            <p className="text-warm-800 font-medium mb-1">确认删除文档</p>
            <p className="text-xs text-warm-500 mb-4 truncate">{deleteConfirm.file}</p>
            <div className="flex gap-3 justify-center">
              <button className="btn-secondary text-sm" onClick={() => setDeleteConfirm(null)}>取消</button>
              <button className="btn-danger text-sm" onClick={handleDelete} disabled={deleting}>
                {deleting ? '删除中…' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.95 }}
            className={`fixed bottom-6 right-6 px-5 py-3.5 rounded-2xl text-sm font-medium z-50 shadow-warm-md ${
              toast.type === 'error' ? 'toast-error' : toast.type === 'success' ? 'toast-success' : 'toast-info'
            }`}>
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
