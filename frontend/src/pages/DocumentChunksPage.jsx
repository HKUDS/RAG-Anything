import { memo, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle, ArrowLeft, Check, Download, FileText, ImageIcon,
  Pencil, RotateCcw, Search, Sigma, Table, Tag, Trash2, Video, X, Zap,
} from 'lucide-react'
import { api, getToken, setCurrentKB } from '../utils/api'
import { getChunkingStrategyPresentation } from '../utils/chunkingStrategyPresentation'
import { useAuth } from '../context/AuthContext'
import { UserDialogConfirmation } from '../components/UserDialog'

const STATUS_LABELS = {
  queued: '排队中',
  processed: '已完成',
  processing: '处理中',
  handling: '入库中',
  completed: '已完成',
  failed: '失败',
}

const TYPE_META = {
  image: { label: '图片', icon: ImageIcon },
  table: { label: '表格', icon: Table },
  equation: { label: '公式', icon: Sigma },
  video: { label: '视频', icon: Video },
}

function formatNumber(value) {
  const number = Number(value || 0)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : '0'
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 19)
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}

function detectChunkType(chunk) {
  if (chunk.original_type) return String(chunk.original_type).toLowerCase()
  const content = String(chunk.content || '').toLowerCase()
  if (content.includes('image content analysis')) return 'image'
  if (content.includes('table analysis')) return 'table'
  if (content.includes('mathematical equation analysis')) return 'equation'
  if (content.includes('video content analysis')) return 'video'
  return ''
}

function chunkSummary(content) {
  const normalized = String(content || '').replace(/\s+/g, ' ').trim()
  return normalized.length > 360 ? `${normalized.slice(0, 360)}...` : normalized
}

function mediaSource(chunk, token) {
  if (chunk.media_url) return chunk.media_url
  if (!chunk.media_path) return ''
  return `/api/files/image?path=${encodeURIComponent(chunk.media_path)}&token=${encodeURIComponent(token)}`
}

function MediaPreview({ chunk, type }) {
  const [failed, setFailed] = useState(false)
  const source = mediaSource(chunk, getToken())

  useEffect(() => setFailed(false), [chunk.chunk_id, source])

  if (!source || failed) {
    return <div className="chunk-media-fallback" role="status"><ImageIcon size={20} aria-hidden="true" /><span>{failed ? '媒体预览加载失败' : '该切块没有可用的媒体预览'}</span></div>
  }
  if (type === 'video') {
    return <video className="chunk-media-preview" controls preload="metadata" onError={() => setFailed(true)}><source src={source} /></video>
  }
  return <img className="chunk-media-preview" src={source} alt={chunk.modal_entity_name || '切块媒体预览'} loading="lazy" onError={() => setFailed(true)} />
}

function detailPath(kbName, docId, chunkId, tagId, mode = '') {
  const params = new URLSearchParams()
  if (tagId) params.set('tag', tagId)
  if (mode) params.set('mode', mode)
  const query = params.toString()
  const basePath = `/knowledge/${encodeURIComponent(kbName)}/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}`
  return query ? `${basePath}?${query}` : basePath
}

const ChunkItem = memo(function ChunkItem({
  chunk,
  kbName,
  displayIndex,
  canWrite,
  isOnlyChunk,
  deleting,
  onOpen,
  onStartEdit,
  onRequestDelete,
}) {
  const type = detectChunkType(chunk)
  const typeMeta = TYPE_META[type]
  const TypeIcon = typeMeta?.icon
  const summary = chunkSummary(chunk.content)

  return (
    <article className="chunk-list-item" aria-labelledby={`chunk-card-title-${chunk.chunk_id}`}>
      <div className="chunk-card-header">
        <h4 className="chunk-list-number" id={`chunk-card-title-${chunk.chunk_id}`}>#{displayIndex}</h4>
        <div className="chunk-card-badges">
          <span className="chunk-card-status"><Check size={12} aria-hidden="true" />可检索</span>
          {TypeIcon ? <span><TypeIcon size={12} aria-hidden="true" />{typeMeta.label}</span> : null}
        </div>
      </div>

      {typeMeta || chunk.is_multimodal ? <div className="chunk-card-media"><MediaPreview chunk={chunk} type={type} /></div> : null}

      <button type="button" className="chunk-card-preview" onClick={() => onOpen(chunk)} aria-label={`查看第 ${displayIndex} 个切块全文`}>
        <span className="chunk-preview-text">{summary || '空内容'}</span>
      </button>

      <div className="chunk-card-tags" aria-label="切块信息">
        <span><Zap size={12} aria-hidden="true" />{formatNumber(chunk.tokens)} tokens</span>
        {chunk.page_idx != null ? <span>第 {chunk.page_idx} 页</span> : null}
        {chunk.modal_entity_name ? <span title={chunk.modal_entity_name}>{chunk.modal_entity_name}</span> : null}
        {(chunk.tags || []).slice(0, 2).map(tag => <Link key={tag.id} to={`/knowledge/${encodeURIComponent(kbName)}?tab=tags&tag=${encodeURIComponent(tag.id)}`} className="chunk-topic-tag"><Tag size={12} aria-hidden="true" />{tag.name}</Link>)}
        {(chunk.tags || []).length > 2 ? <span className="chunk-topic-tag">+{chunk.tags.length - 2}</span> : null}
      </div>

      <div className="chunk-card-footer">
        <span>{formatNumber(String(chunk.content || '').length)} 字</span>
        <div className="chunk-card-actions">
          <button type="button" className="btn-ghost" onClick={() => onOpen(chunk)}>查看</button>
          {canWrite ? <>
            <button type="button" className="btn-ghost" onClick={() => onStartEdit(chunk)} disabled={deleting}><Pencil size={14} aria-hidden="true" />编辑</button>
            <button type="button" className="btn-ghost chunk-card-delete" onClick={() => onRequestDelete(chunk)} disabled={isOnlyChunk || deleting} title={isOnlyChunk ? '最后一个切块不能删除' : '删除切块'}><Trash2 size={14} aria-hidden="true" /></button>
          </> : null}
        </div>
      </div>
    </article>
  )
})

function PageSkeleton() {
  return <div className="chunk-page-skeleton" aria-label="正在加载切块详情" aria-busy="true"><div className="skeleton h-16 w-full" /><div className="skeleton h-14 w-full" />{[1, 2, 3, 4].map(item => <div key={item} className="skeleton h-20 w-full" />)}</div>
}

function ErrorState({ error, onRetry, backPath }) {
  const isForbidden = error?.status === 403
  const isMissing = error?.status === 404
  const title = isForbidden ? '无权访问此文档' : isMissing ? '文档不存在' : '切块详情加载失败'
  const description = isForbidden ? '你的角色没有访问该知识库文档的权限。' : isMissing ? '文档可能已被删除，或当前链接已经失效。' : (error?.message || '网络连接异常，请稍后重试。')
  return (
    <div className="chunk-page-state" role="alert">
      <AlertTriangle size={30} aria-hidden="true" />
      <h2>{title}</h2>
      <p>{description}</p>
      <div className="chunk-action-group">
        <Link className="btn-secondary" to={backPath}><ArrowLeft size={15} aria-hidden="true" />返回知识库</Link>
        {!isForbidden && !isMissing ? <button type="button" className="btn-primary" onClick={onRetry}><RotateCcw size={15} aria-hidden="true" />重新加载</button> : null}
      </div>
    </div>
  )
}

export default function DocumentChunksPage() {
  const { kbName = '', docId = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { hasPermission } = useAuth()
  const canWrite = hasPermission('kb:write')
  const navigationDoc = location.state?.doc || null
  const selectedTagId = searchParams.get('tag')
  const legacyChunkId = searchParams.get('chunk')
  const backPath = selectedTagId ? `/knowledge/${encodeURIComponent(kbName)}?tab=tags&tag=${encodeURIComponent(selectedTagId)}` : `/knowledge/${encodeURIComponent(kbName)}`

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [query, setQuery] = useState('')
  const deferredQuery = useDeferredValue(query)
  const [deleteCandidate, setDeleteCandidate] = useState(null)
  const [deletingId, setDeletingId] = useState('')
  const [toast, setToast] = useState(null)
  const toastTimerRef = useRef(null)

  useEffect(() => {
    setCurrentKB(kbName)
  }, [kbName])

  useEffect(() => {
    if (!legacyChunkId) return
    navigate(detailPath(kbName, docId, legacyChunkId, selectedTagId), { replace: true })
  }, [docId, kbName, legacyChunkId, navigate, selectedTagId])

  useEffect(() => {
    if (legacyChunkId) return undefined
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setError(null)
    api.getDocumentChunks(docId, { kb: kbName, signal: controller.signal })
      .then(result => {
        if (active) setData({ ...result, chunks: Array.isArray(result.chunks) ? result.chunks : [] })
      })
      .catch(requestError => {
        if (active) setError(requestError)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [docId, kbName, legacyChunkId, reloadKey])

  useEffect(() => () => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
  }, [])

  const showToast = useCallback((message, type = 'info') => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    setToast({ message, type })
    toastTimerRef.current = setTimeout(() => setToast(null), 3500)
  }, [])

  const chunks = data?.chunks || []
  const normalizedQuery = deferredQuery.trim().toLocaleLowerCase('zh-CN')
  const scopedChunks = useMemo(() => {
    if (!selectedTagId) return chunks
    return chunks.filter(chunk => (chunk.tags || []).some(tag => String(tag.id) === String(selectedTagId)))
  }, [chunks, selectedTagId])
  const filteredChunks = useMemo(() => {
    if (!normalizedQuery) return scopedChunks
    return scopedChunks.filter(chunk => [chunk.content, chunk.chunk_id, chunk.modal_entity_name, chunk.original_type, chunk.page_idx].filter(value => value != null).join(' ').toLocaleLowerCase('zh-CN').includes(normalizedQuery))
  }, [normalizedQuery, scopedChunks])

  const document = data?.document || navigationDoc || {}
  const filename = document.file || navigationDoc?.file || '未命名文档'
  const strategy = getChunkingStrategyPresentation(document.chunking_strategy)
  const total = data?.total ?? chunks.length
  const totalTokens = data?.total_tokens ?? chunks.reduce((sum, chunk) => sum + Number(chunk.tokens || 0), 0)

  const openChunk = useCallback(chunk => {
    navigate(detailPath(kbName, docId, chunk.chunk_id, selectedTagId))
  }, [docId, kbName, navigate, selectedTagId])

  const startEdit = useCallback(chunk => {
    navigate(detailPath(kbName, docId, chunk.chunk_id, selectedTagId, 'edit'))
  }, [docId, kbName, navigate, selectedTagId])

  const deleteChunk = useCallback(async () => {
    if (!deleteCandidate || deletingId) return
    setDeletingId(deleteCandidate.chunk_id)
    try {
      const result = await api.deleteDocumentChunk(docId, deleteCandidate.chunk_id, { kb: kbName })
      setData(previous => ({
        ...previous,
        chunks: previous.chunks.filter(item => item.chunk_id !== deleteCandidate.chunk_id),
        total: result.total ?? Math.max(0, (previous.total ?? previous.chunks.length) - 1),
        total_tokens: result.total_tokens ?? Math.max(0, (previous.total_tokens ?? 0) - Number(deleteCandidate.tokens || 0)),
        graph_sync_state: result.graph_sync_state ?? 'stale',
      }))
      setDeleteCandidate(null)
      showToast('切块已永久删除，检索索引已刷新。', 'success')
    } catch (mutationError) {
      showToast(mutationError.message || '切块删除失败', 'error')
    } finally {
      setDeletingId('')
    }
  }, [deleteCandidate, deletingId, docId, kbName, showToast])

  if (loading) return <PageSkeleton />
  if (error) return <ErrorState error={error} onRetry={() => setReloadKey(value => value + 1)} backPath={backPath} />

  return (
    <div className="chunk-maintenance-page">
      <header className="chunk-page-header">
        <div className="chunk-document-bar">
          <div className="chunk-document-identity">
            <Link to={backPath} className="chunk-back-link" aria-label={`返回知识库 ${kbName}`}><ArrowLeft size={17} aria-hidden="true" /><span>返回</span></Link>
            <span className="chunk-document-divider" aria-hidden="true" />
            <FileText size={18} aria-hidden="true" className="chunk-document-icon" />
            <h2 title={filename}>{filename}</h2>
            <span className="chunk-count-badge">{formatNumber(total)} 个切块</span>
          </div>
          <div className="chunk-document-controls">
            <dl className="chunk-document-meta">
              <div><dt>状态</dt><dd><span className={`chunk-status ${document.status || 'unknown'}`}><Check size={12} aria-hidden="true" />{STATUS_LABELS[document.status] || document.status || '-'}</span></dd></div>
              <div><dt>切块方式</dt><dd title={strategy.description}>{strategy.name}</dd></div>
              <div><dt>Tokens</dt><dd>{formatNumber(totalTokens)}</dd></div>
              <div><dt>更新时间</dt><dd>{formatDate(document.updated || navigationDoc?.updated)}</dd></div>
            </dl>
            {filename !== '未命名文档' ? <a className="btn-secondary chunk-download-link" href={api.downloadDocumentUrl(docId, kbName)} download aria-label="原文下载" title="原文下载"><Download size={15} aria-hidden="true" /><span>原文下载</span></a> : null}
          </div>
        </div>
      </header>

      {data?.graph_sync_state === 'stale' ? <div className="chunk-sync-warning" role="status"><AlertTriangle size={18} aria-hidden="true" /><div><strong>知识图谱需要后续同步</strong><p>文本与向量检索已更新；实体关系图及派生视觉索引不会自动同步。</p></div></div> : null}
      {!canWrite ? <div className="chunk-readonly-notice" role="status">当前账号拥有只读权限。你可以搜索和查看切块，但不能编辑或删除。</div> : null}

      <section className="chunk-list-section" aria-labelledby="chunk-list-heading">
        <div className="chunk-toolbar">
          <div className="chunk-toolbar-copy"><h3 id="chunk-list-heading">切块列表</h3><span>{normalizedQuery ? `显示 ${filteredChunks.length} / ${scopedChunks.length}` : selectedTagId ? `当前标签关联 ${scopedChunks.length} 个切块` : `共 ${chunks.length} 个切块`}</span></div>
          <div className="chunk-toolbar-controls">
            <label className="chunk-search-field"><Search size={16} aria-hidden="true" /><span className="sr-only">搜索切块</span><input type="search" name="chunk-search" autoComplete="off" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索正文、ID、页码或媒体类型" />{query ? <button type="button" onClick={() => setQuery('')} aria-label="清空搜索"><X size={15} /></button> : null}</label>
          </div>
        </div>

        {chunks.length === 0 ? <div className="chunk-page-state"><FileText size={30} aria-hidden="true" /><h3>该文档还没有切块</h3><p>文档处理完成后，切块会显示在这里。</p></div> : filteredChunks.length === 0 ? <div className="chunk-page-state"><Search size={30} aria-hidden="true" /><h3>没有匹配的切块</h3><p>尝试缩短关键词，或搜索切块 ID、页码和媒体类型。</p><button type="button" className="btn-secondary" onClick={() => setQuery('')}>清除搜索</button></div> : (
          <div className="chunk-list">
            {filteredChunks.map((chunk, index) => <ChunkItem key={chunk.chunk_id} chunk={chunk} kbName={kbName} displayIndex={chunk.chunk_order_index != null ? Number(chunk.chunk_order_index) + 1 : index + 1} canWrite={canWrite} isOnlyChunk={total <= 1} deleting={deletingId === chunk.chunk_id} onOpen={openChunk} onStartEdit={startEdit} onRequestDelete={setDeleteCandidate} />)}
          </div>
        )}
      </section>

      <UserDialogConfirmation isOpen={Boolean(deleteCandidate)} title="确认永久删除此切块" description="删除后会立即从文本与向量检索中移除，且无法撤销。" confirmLabel={deletingId ? '删除中' : '永久删除'} cancelLabel="取消" onConfirm={deleteChunk} onCancel={() => !deletingId && setDeleteCandidate(null)} danger confirmDisabled={Boolean(deletingId)} closeDisabled={Boolean(deletingId)} lockScroll />
      {toast ? <div className={`chunk-page-toast ${toast.type}`} role="status" aria-live="polite">{toast.message}</div> : null}
    </div>
  )
}
