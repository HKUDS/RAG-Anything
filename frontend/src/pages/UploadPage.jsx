import { useState, useCallback, useEffect, useRef } from 'react'
import { Upload, ClipboardPaste, FileText, Loader2, CheckCircle2, XCircle, FolderOpen, Globe } from 'lucide-react'
import { motion } from 'framer-motion'
import { api } from '../utils/api'
import ChunkingStrategySelector from '../components/ChunkingStrategySelector'
import { getChunkingStrategyPresentation } from '../utils/chunkingStrategyPresentation'

const SUPPORTED = '.pdf .jpg .jpeg .png .bmp .tiff .gif .webp .doc .docx .ppt .pptx .xls .xlsx .txt .md'.split(' ')

export default function UploadPage({ onToast }) {
  const [dragOver, setDragOver] = useState(false)
  const [files, setFiles] = useState([])
  const [urlInput, setUrlInput] = useState('')
  const [urlLoading, setUrlLoading] = useState(false)
  const [pasteContent, setPasteContent] = useState('')
  const [pasteTitle, setPasteTitle] = useState('')
  const [folderPath, setFolderPath] = useState('')
  const [folderLoading, setFolderLoading] = useState(false)
  const [wsProgress, setWsProgress] = useState({})
  const [chunkingStrategy, setChunkingStrategy] = useState('')
  const [strategies, setStrategies] = useState({})
  const wsRef = useRef(null)

  useEffect(() => {
    api.getPersonalSettings().then(s => {
      if (s?.effective?.ingestion?.chunking_strategy) setChunkingStrategy(s.effective.ingestion.chunking_strategy)
    }).catch(err => console.error('加载分块策略失败:', err))
  }, [])

  useEffect(() => {
    const poll = async () => {
      try {
        const data = await api.getStatus()
        if (data.tasks) {
          const progress = {}
          data.tasks.forEach(t => { progress[t.id] = t })
          setWsProgress(progress)
        }
      } catch { /* 轮询失败时静默等待下次重试 */ }
    }
    poll()
    const timer = setInterval(poll, 3000)
    return () => clearInterval(timer)
  }, [])

  const addFile = useCallback((file) => {
    setFiles(prev => [...prev, { name: file.name, size: file.size, file, status: 'pending' }])
  }, [])

  const processFile = async (idx) => {
    setFiles(prev => prev.map((f, i) => i === idx ? { ...f, status: 'uploading' } : f))
    try {
      const res = await api.uploadFile(files[idx].file, chunkingStrategy)
      setFiles(prev => prev.map((f, i) => i === idx ? {
        ...f,
        status: 'done',
        taskId: res.task_id,
        chunkingStrategy: res.chunking_strategy || chunkingStrategy,
      } : f))
      onToast?.(`${files[idx].name} 上传成功`, 'success')
    } catch (e) {
      setFiles(prev => prev.map((f, i) => i === idx ? { ...f, status: 'error', error: e.message } : f))
      onToast?.(`${files[idx].name} 失败: ${e.message}`, 'error')
    }
  }

  const processAllFiles = async () => {
    const pending = files
      .map((f, i) => ({ ...f, idx: i }))
      .filter(f => f.status === 'pending')
    if (pending.length === 0) return

    setFiles(prev => prev.map(f =>
      f.status === 'pending' ? { ...f, status: 'uploading' } : f
    ))
    let ok = 0, fail = 0
    for (const { idx } of pending) {
      const f = files[idx]
      try {
        const res = await api.uploadFile(f.file, chunkingStrategy)
        setFiles(prev => prev.map((x, i) => i === idx ? {
          ...x,
          status: 'done',
          taskId: res.task_id,
          chunkingStrategy: res.chunking_strategy || chunkingStrategy,
        } : x))
        ok++
      } catch (e) {
        setFiles(prev => prev.map((x, i) => i === idx ? { ...x, status: 'error', error: e.message } : x))
        fail++
      }
    }
    onToast?.(`批量上传完成: ${ok} 成功, ${fail} 失败`, fail > 0 ? 'error' : 'success')
  }

  const handleDrop = useCallback((e) => {
    e.preventDefault(); setDragOver(false)
    Array.from(e.dataTransfer.files).forEach(addFile)
  }, [addFile])

  const handlePaste = async () => {
    if (!pasteContent.trim()) return
    try {
      await api.uploadContent(pasteContent, pasteTitle || '粘贴内容', chunkingStrategy)
      onToast?.('内容已入库', 'success')
      setPasteContent(''); setPasteTitle('')
    } catch (e) { onToast?.(e.message, 'error') }
  }

  const handleUrlImport = async () => {
    if (!urlInput.trim()) return
    setUrlLoading(true)
    try {
      const strategyParam = chunkingStrategy ? `&chunking_strategy=${chunkingStrategy}` : ''
      const res = await fetch(`/api/upload/url?url=${encodeURIComponent(urlInput)}${strategyParam}`, { method: 'POST' })
      if (!res.ok) throw new Error((await res.json()).detail || '导入失败')
      onToast?.('URL 文档导入成功', 'success')
      setUrlInput('')
    } catch (e) { onToast?.(`URL 导入失败: ${e.message}`, 'error') }
    setUrlLoading(false)
  }

  const handleFolderUpload = async () => {
    if (!folderPath.trim()) return
    setFolderLoading(true)
    try {
      await api.uploadFolder(folderPath, chunkingStrategy)
      onToast?.('文件夹处理完成', 'success')
    } catch (e) { onToast?.(`文件夹处理失败: ${e.message}`, 'error') }
    setFolderLoading(false)
  }

  return (
    <div className="space-y-8">
      <div className="page-header page-header-divider">
        <div>
          <h2 className="page-title">文档上传</h2>
          <p className="page-subtitle">支持多种文件格式，拖拽或点击上传</p>
        </div>
      </div>

      {/* 拖拽上传 */}
      <motion.div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`card border-dashed p-12 text-center cursor-pointer transition-all dark:bg-sky-900/20 dark:border-sky-800/30 ${
          dragOver ? 'border-sky-400 bg-sky-50/50 dark:bg-sky-900/40 shadow-cloud-md' : 'border-cloud-400/70'
        }`}
        onClick={() => document.getElementById('file-input').click()}
        role="button"
        aria-label="点击或拖拽上传文件"
      >
        <input id="file-input" type="file" multiple className="hidden"
          onChange={(e) => Array.from(e.target.files).forEach(addFile)} />
        <Upload size={40} className="mx-auto mb-4 text-ink-muted dark:text-cloud-500" />
        <p className="text-ink-body dark:text-cloud-300 font-medium">拖拽文件到此处，或点击选择</p>
        <p className="text-ink-muted dark:text-cloud-500 text-sm mt-2">支持 PDF、Word、PPT、Excel、图片、文本</p>
        <div className="flex flex-wrap justify-center gap-1.5 mt-3">
          {SUPPORTED.slice(0, 8).map(ext => (
            <span key={ext} className="text-2xs px-2 py-0.5 rounded-lg bg-cloud-100 dark:bg-sky-900/30 text-ink-muted dark:text-cloud-500 font-mono">{ext}</span>
          ))}
          <span className="text-2xs px-2 py-0.5 rounded-lg bg-cloud-100 dark:bg-sky-900/30 text-ink-muted dark:text-cloud-500">+9 more</span>
        </div>
      </motion.div>

      {/* 切块方式 */}
      <div className="card p-4 space-y-3 dark:bg-sky-900/20 dark:border-sky-800/30">
        <ChunkingStrategySelector
          strategies={strategies}
          value={chunkingStrategy}
          onChange={setChunkingStrategy}
        />
      </div>

      {/* 链接、文件夹与粘贴输入行 */}
      <div className="grid grid-cols-3 gap-5">
        <div className="card p-4 space-y-3 dark:bg-sky-900/20 dark:border-sky-800/30">
          <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300"><Globe size={16}/>URL 导入</h3>
          <input className="input-field text-sm" placeholder="https://example.com/doc.pdf" value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleUrlImport()} maxLength={2048} />
          <button className="btn-primary text-sm w-full" onClick={handleUrlImport} disabled={!urlInput || urlLoading}>
            {urlLoading ? <Loader2 size={14} className="animate-spin inline"/> : '导入'}
          </button>
        </div>
        <div className="card p-4 space-y-3 dark:bg-sky-900/20 dark:border-sky-800/30">
          <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300"><FolderOpen size={16}/>文件夹上传</h3>
          <input className="input-field text-sm" placeholder="D:\我的文档" value={folderPath}
            onChange={(e) => setFolderPath(e.target.value)} />
          <button className="btn-primary text-sm w-full" onClick={handleFolderUpload} disabled={!folderPath || folderLoading}>
            {folderLoading ? <Loader2 size={14} className="animate-spin inline"/> : '开始处理'}
          </button>
        </div>
        <div className="card p-4 space-y-3 dark:bg-sky-900/20 dark:border-sky-800/30">
          <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300"><ClipboardPaste size={16}/>粘贴内容</h3>
          <input className="input-field text-sm" placeholder="标题（可选）" value={pasteTitle}
            onChange={(e) => setPasteTitle(e.target.value)} maxLength={128} />
          <textarea className="input-field text-sm h-20 resize-none" placeholder="在此粘贴文本内容…" value={pasteContent}
            onChange={(e) => setPasteContent(e.target.value)} />
          <button className="btn-primary text-sm w-full" onClick={handlePaste} disabled={!pasteContent.trim()}>提交</button>
        </div>
      </div>

      {/* 文件列表 */}
      {files.length > 0 && (
        <div className="card p-4 space-y-2 dark:bg-sky-900/20 dark:border-sky-800/30">
          <div className="flex items-center justify-between">
            <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300"><FileText size={16}/>文件列表 ({files.length})</h3>
            {files.some(f => f.status === 'pending') && (
              <button className="btn-primary text-xs py-1.5 px-3" onClick={processAllFiles}>
                一键全部上传 ({files.filter(f => f.status === 'pending').length})
              </button>
            )}
          </div>
          {files.map((f, i) => (
            <div key={i} className="flex items-center justify-between px-4 py-2.5 bg-cloud-100 dark:bg-sky-900/30 rounded-xl">
              <div className="flex items-center gap-3">
                {f.status === 'uploading' ? <Loader2 size={18} className="animate-spin text-sky-500" />
                  : f.status === 'done' ? <CheckCircle2 size={18} className="text-sage-500" />
                  : f.status === 'error' ? <XCircle size={18} className="text-rose-500" />
                  : <FileText size={18} className="text-ink-muted dark:text-cloud-500" />}
                <div>
                  <p className="text-sm text-ink-body dark:text-cloud-300">{f.name}</p>
                  {f.chunkingStrategy && (
                    <p className="mt-1 text-xs text-ink-muted dark:text-cloud-500">
                      切块：{getChunkingStrategyPresentation(f.chunkingStrategy).name}
                    </p>
                  )}
                  {f.error && <p className="text-xs text-rose-500">{f.error}</p>}
                  {f.status === 'uploading' && f.taskId && wsProgress[f.taskId] && (
                    <div className="mt-1 w-32 h-1 bg-cloud-200 dark:bg-sky-900/50 rounded-full overflow-hidden">
                      <div className="h-full bg-sky-500 rounded-full transition-all" style={{width: `${wsProgress[f.taskId]?.progress || 0}%`}}/>
                    </div>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-ink-muted dark:text-cloud-500 font-mono">{(f.size / 1024).toFixed(0)} KB</span>
                {f.status === 'pending' && <button className="btn-primary text-xs py-1 px-3" onClick={() => processFile(i)}>上传</button>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
