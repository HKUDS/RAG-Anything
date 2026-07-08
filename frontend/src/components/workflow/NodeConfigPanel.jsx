import { useState, useEffect, useRef } from 'react'
import { X, Upload, RefreshCw } from 'lucide-react'
import { getNodeType } from './nodeTypes'

function getToken() {
  try { const saved = localStorage.getItem('raganything_auth'); return saved ? JSON.parse(saved).token : '' } catch { return '' }
}

function ModelSelect({ value, onChange, modelType = 'llm' }) {
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/workflows/models?type=${modelType}`, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then(r => r.json())
      .then(data => { if (!cancelled) setModels(data.models || []) })
      .catch(err => console.error(err))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [modelType])

  return (
    <div>
      <select
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        className="w-full text-xs px-3 py-2 rounded-lg border border-cloud-300 bg-white
                   focus:outline-none focus:ring-2 focus:ring-sky-200 focus:border-sky-400 text-ink-body"
      >
        <option value="">默认（服务器配置）</option>
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}{m.source === 'fallback' ? '' : ''}
          </option>
        ))}
      </select>
      {loading && <p className="text-2xs text-ink-muted mt-1">加载中...</p>}
    </div>
  )
}

function FilePicker({ value, onChange, filterType }) {
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef(null)

  const fetchFiles = async () => {
    setLoading(true)
    try {
      const suffix = filterType === '全部' ? '' : filterType
      const res = await fetch(`/api/workflows/files?file_type=${suffix}`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      })
      if (res.ok) {
        const data = await res.json()
        setFiles(data.files || [])
      }
    } catch { /* 无需处理 */ } finally { setLoading(false) }
  }

  useEffect(() => { fetchFiles() }, [filterType])

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const fd = new FormData(); fd.append('file', file)
      const res = await fetch('/api/workflows/upload', {
        method: 'POST', headers: { Authorization: `Bearer ${getToken()}` }, body: fd,
      })
      if (res.ok) {
        await fetchFiles()
        const data = await res.json()
        onChange(data.filename)
      }
    } catch { /* 无需处理 */ } finally { setUploading(false) }
  }

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes}B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-1.5">
        <select
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1 text-xs px-2 py-2 rounded-lg border border-cloud-300 bg-white
                     focus:outline-none focus:ring-2 focus:ring-sky-200 focus:border-sky-400 text-ink-body"
        >
          <option value="">自动选择（最新文件）</option>
          {files.map((f) => (
            <option key={f.name} value={f.name}>{f.name} ({formatSize(f.size)})</option>
          ))}
        </select>
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="flex items-center justify-center w-8 h-9 rounded-lg border border-cloud-300
                     hover:bg-cloud-200 text-ink-muted disabled:opacity-50 transition-colors"
          title="上传文件"
        >
          {uploading ? <RefreshCw size={14} className="animate-spin" /> : <Upload size={14} />}
        </button>
        <input ref={fileInputRef} type="file" className="hidden" onChange={handleUpload}
               accept={filterType === '全部' ? '*' : filterType} />
      </div>
      {loading && <p className="text-2xs text-ink-muted">加载文件列表...</p>}
      {value && <p className="text-2xs text-emerald-600">已选择: {value}</p>}
    </div>
  )
}

export default function NodeConfigPanel({ node, onClose, onUpdate }) {
  if (!node) return null

  const def = getNodeType(node.data?.nodeType)
  if (!def) return null

  // 根据节点类型决定模型类别
  const modelCategory = node.data?.nodeType === 'embedding' ? 'embed' : 'llm'

  const handleChange = (key, value) => {
    onUpdate?.(node.id, { ...node.data, [key]: value })
  }

  return (
    <div className="w-64 flex-shrink-0 bg-white border-l border-cloud-300 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-cloud-200">
        <h3 className="text-sm font-semibold text-ink-body">节点配置</h3>
        <button onClick={onClose} className="p-1 rounded-lg hover:bg-cloud-100 text-ink-muted transition-colors">
          <X size={16} />
        </button>
      </div>

      <div className="px-4 py-2.5 border-b border-cloud-200 flex items-center gap-2">
        <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: def.color }} />
        <span className="text-xs text-ink-muted">{def.label}</span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {def.configFields.map((field) => (
          <div key={field.key}>
            <label className="block text-xs font-medium text-ink-body mb-1.5">{field.label}</label>

            {field.type === 'file_picker' ? (
              <FilePicker
                value={node.data[field.key] ?? ''}
                onChange={(v) => handleChange(field.key, v)}
                filterType={field.filterKey ? node.data[field.filterKey] : '.pdf'}
              />
            ) : field.type === 'model_select' ? (
              <ModelSelect
                value={node.data[field.key] ?? ''}
                onChange={(v) => handleChange(field.key, v)}
                modelType={modelCategory}
              />
            ) : field.type === 'select' ? (
              <select value={node.data[field.key] ?? field.default}
                onChange={(e) => handleChange(field.key, e.target.value)}
                className="w-full text-xs px-3 py-2 rounded-lg border border-cloud-300 bg-white
                           focus:outline-none focus:ring-2 focus:ring-sky-200 focus:border-sky-400 text-ink-body">
                {field.options.map((opt) => (<option key={opt} value={opt}>{opt}</option>))}
              </select>
            ) : field.type === 'textarea' ? (
              <textarea value={node.data[field.key] ?? field.default}
                onChange={(e) => handleChange(field.key, e.target.value)} rows={4}
                placeholder="输入系统提示词..."
                className="w-full text-xs px-3 py-2 rounded-lg border border-cloud-300
                           focus:outline-none focus:ring-2 focus:ring-sky-200 focus:border-sky-400
                           text-ink-body resize-y font-mono" />
            ) : field.type === 'number' ? (
              <input type="number" value={node.data[field.key] ?? field.default}
                onChange={(e) => handleChange(field.key, Number(e.target.value))}
                min={field.min} max={field.max} step={field.step}
                className="w-full text-xs px-3 py-2 rounded-lg border border-cloud-300
                           focus:outline-none focus:ring-2 focus:ring-sky-200 focus:border-sky-400 text-ink-body" />
            ) : (
              <input type={field.type} value={node.data[field.key] ?? field.default}
                onChange={(e) => handleChange(field.key, e.target.value)}
                className="w-full text-xs px-3 py-2 rounded-lg border border-cloud-300
                           focus:outline-none focus:ring-2 focus:ring-sky-200 focus:border-sky-400 text-ink-body" />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
