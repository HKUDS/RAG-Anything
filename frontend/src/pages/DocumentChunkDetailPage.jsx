import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle, ArrowLeft, FileText, ImageIcon, Loader2, Pencil,
  Save, Sigma, Table, Tag, Trash2, Video, X, Zap,
} from 'lucide-react'
import { api, getToken, setCurrentKB } from '../utils/api'
import { useAuth } from '../context/AuthContext'
import { UserDialogConfirmation } from '../components/UserDialog'

const MAX_CONTENT_LENGTH = 8000

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

function detectChunkType(chunk) {
  if (chunk.original_type) return String(chunk.original_type).toLowerCase()
  const content = String(chunk.content || '').toLowerCase()
  if (content.includes('image content analysis')) return 'image'
  if (content.includes('table analysis')) return 'table'
  if (content.includes('mathematical equation analysis')) return 'equation'
  if (content.includes('video content analysis')) return 'video'
  return ''
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
    return (
      <div className="chunk-media-fallback" role="status">
        <ImageIcon size={20} aria-hidden="true" />
        <span>{failed ? '媒体预览加载失败' : '该切块没有可用的媒体预览'}</span>
      </div>
    )
  }

  if (type === 'video') {
    return (
      <video className="chunk-media-preview" controls preload="metadata" onError={() => setFailed(true)}>
        <source src={source} />
      </video>
    )
  }

  return (
    <img
      className="chunk-media-preview"
      src={source}
      alt={chunk.modal_entity_name || '切块媒体预览'}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  )
}

function listPath(kbName, docId, tagId) {
  const basePath = `/knowledge/${encodeURIComponent(kbName)}/documents/${encodeURIComponent(docId)}/chunks`
  return tagId ? `${basePath}?tag=${encodeURIComponent(tagId)}` : basePath
}

function detailPath(kbName, docId, chunkId, tagId) {
  const basePath = `${listPath(kbName, docId)}/${encodeURIComponent(chunkId)}`
  return tagId ? `${basePath}?tag=${encodeURIComponent(tagId)}` : basePath
}

function DetailErrorState({ error, onRetry, backPath }) {
  const missing = error?.status === 404
  const forbidden = error?.status === 403
  const title = missing ? '切块不存在' : forbidden ? '无权查看此切块' : '切块详情加载失败'
  const description = missing
    ? '该切块可能已被删除或在编辑后更新了地址。'
    : forbidden
      ? '当前账号没有访问该知识库的权限。'
      : (error?.message || '网络连接异常，请稍后重试。')

  return (
    <div className="chunk-page-state" role="alert">
      <AlertTriangle size={30} aria-hidden="true" />
      <h2>{title}</h2>
      <p>{description}</p>
      <div className="chunk-action-group">
        <Link className="btn-secondary" to={backPath}><ArrowLeft size={15} aria-hidden="true" />返回切块列表</Link>
        {!missing && !forbidden ? <button type="button" className="btn-primary" onClick={onRetry}>重新加载</button> : null}
      </div>
    </div>
  )
}

export default function DocumentChunkDetailPage() {
  const { kbName = '', docId = '', chunkId = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { hasPermission } = useAuth()
  const canWrite = hasPermission('kb:write')
  const selectedTagId = searchParams.get('tag')
  const isEditing = canWrite && searchParams.get('mode') === 'edit'
  const backPath = listPath(kbName, docId, selectedTagId)
  const navigationDoc = location.state?.doc || null

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [knownTags, setKnownTags] = useState([])
  const [tagInput, setTagInput] = useState('')
  const [savingTags, setSavingTags] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [toast, setToast] = useState(null)
  const toastTimerRef = useRef(null)

  useEffect(() => {
    setCurrentKB(kbName)
  }, [kbName])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setError(null)

    api.getDocumentChunk(docId, chunkId, { kb: kbName, signal: controller.signal })
      .then(result => {
        if (active) setData(result)
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
  }, [chunkId, docId, kbName, reloadKey])

  useEffect(() => {
    const controller = new AbortController()
    api.listKnowledgeTags({ kb: kbName, signal: controller.signal })
      .then(result => setKnownTags(Array.isArray(result.tags) ? result.tags : []))
      .catch(() => {})
    return () => controller.abort()
  }, [kbName])

  useEffect(() => () => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
  }, [])

  const showToast = useCallback((message, type = 'info') => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    setToast({ message, type })
    toastTimerRef.current = setTimeout(() => setToast(null), 3500)
  }, [])

  const chunk = data?.chunk || null
  const document = data?.document || navigationDoc || {}
  const total = data?.total ?? 1
  const type = chunk ? detectChunkType(chunk) : ''
  const typeMeta = TYPE_META[type]
  const filename = document.file || '未命名文档'

  useEffect(() => {
    if (isEditing && chunk) setEditValue(chunk.content || '')
  }, [chunk?.chunk_id, isEditing])

  const setEditMode = useCallback((enabled) => {
    const next = new URLSearchParams(searchParams)
    if (enabled) next.set('mode', 'edit')
    else next.delete('mode')
    setSearchParams(next)
  }, [searchParams, setSearchParams])

  const updateTags = useCallback(async (names) => {
    if (!chunk) return
    setSavingTags(true)
    try {
      const result = await api.updateDocumentChunkTags(docId, chunk.chunk_id, names, { kb: kbName })
      const tags = Array.isArray(result.tags) ? result.tags : []
      setData(previous => previous ? { ...previous, chunk: { ...previous.chunk, tags } } : previous)
      setKnownTags(previous => {
        const next = new Map(previous.map(tag => [String(tag.id), tag]))
        tags.forEach(tag => next.set(String(tag.id), {
          ...tag,
          document_count: tag.document_count || 0,
          chunk_count: tag.chunk_count || 0,
        }))
        return [...next.values()].sort((left, right) => left.name.localeCompare(right.name, 'zh-CN'))
      })
      setTagInput('')
    } catch (mutationError) {
      showToast(mutationError.message || '标签保存失败', 'error')
    } finally {
      setSavingTags(false)
    }
  }, [chunk, docId, kbName, showToast])

  const saveChunk = useCallback(async () => {
    if (!chunk || !editValue.trim() || editValue.length > MAX_CONTENT_LENGTH) return
    setSaving(true)
    try {
      const result = await api.updateDocumentChunk(docId, chunk.chunk_id, editValue, { kb: kbName })
      const nextId = result.new_chunk_id || result.chunk?.chunk_id || chunk.chunk_id
      setData(previous => previous ? {
        ...previous,
        chunk: { ...previous.chunk, ...(result.chunk || {}), chunk_id: nextId },
        graph_sync_state: result.graph_sync_state || previous.graph_sync_state,
      } : previous)
      navigate(detailPath(kbName, docId, nextId, selectedTagId), { replace: true })
      showToast('切块已更新，检索索引已刷新。', 'success')
    } catch (mutationError) {
      showToast(mutationError.message || '切块保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }, [chunk, docId, editValue, kbName, navigate, selectedTagId, showToast])

  const deleteChunk = useCallback(async () => {
    if (!chunk || deleting) return
    setDeleting(true)
    try {
      await api.deleteDocumentChunk(docId, chunk.chunk_id, { kb: kbName })
      navigate(backPath, { replace: true })
    } catch (mutationError) {
      setDeleteOpen(false)
      showToast(mutationError.message || '切块删除失败', 'error')
    } finally {
      setDeleting(false)
    }
  }, [backPath, chunk, deleting, docId, kbName, navigate, showToast])

  if (loading) return <div className="chunk-page-skeleton" aria-label="正在加载切块详情" aria-busy="true"><div className="skeleton h-16 w-full" /><div className="skeleton h-96 w-full" /></div>
  if (error || !chunk) return <DetailErrorState error={error || { status: 404 }} onRetry={() => setReloadKey(value => value + 1)} backPath={backPath} />

  return (
    <div className="chunk-detail-page">
      <header className="chunk-detail-page-header">
        <Link to={backPath} className="chunk-back-link" aria-label={`返回 ${filename} 的切块列表`}>
          <ArrowLeft size={17} aria-hidden="true" />
          <span>返回切块列表</span>
        </Link>
        <div className="chunk-detail-page-heading">
          <div>
            <span className="chunk-detail-index">#{Number(chunk.chunk_order_index || 0) + 1}</span>
            <h2>切块详情</h2>
          </div>
          <p title={filename}><FileText size={15} aria-hidden="true" />{filename}</p>
        </div>
        {canWrite ? (
          <div className="chunk-detail-page-actions">
            <button type="button" className="btn-secondary" onClick={() => setEditMode(!isEditing)} disabled={saving}>
              {isEditing ? <X size={15} aria-hidden="true" /> : <Pencil size={15} aria-hidden="true" />}
              {isEditing ? '取消编辑' : '编辑'}
            </button>
            <button type="button" className="btn-danger" onClick={() => setDeleteOpen(true)} disabled={deleting || total <= 1} title={total <= 1 ? '最后一个切块不能删除' : '删除切块'}>
              <Trash2 size={15} aria-hidden="true" />删除
            </button>
          </div>
        ) : null}
      </header>

      <section className="chunk-detail-reading-column" aria-labelledby="chunk-detail-content-heading">
        <div className="chunk-detail-badges" aria-label="切块元数据">
          <span><Zap size={13} aria-hidden="true" />{formatNumber(chunk.tokens)} tokens</span>
          {chunk.page_idx != null ? <span>第 {chunk.page_idx} 页</span> : null}
          <span>{typeMeta?.label || '文本'}</span>
        </div>

        <section className="chunk-tag-editor" aria-labelledby="chunk-tags-heading">
          <div className="chunk-tag-editor-heading">
            <div>
              <h2 id="chunk-tags-heading"><Tag size={15} aria-hidden="true" />关联标签</h2>
              <p>同一标签会将不同文档中的相关切块串联起来。</p>
            </div>
          </div>
          <div className="chunk-tag-list" aria-live="polite">
            {(chunk.tags || []).map(tag => (
              <span key={tag.id} className="chunk-topic-tag">
                <Tag size={12} aria-hidden="true" />{tag.name}
                {canWrite ? <button type="button" onClick={() => updateTags((chunk.tags || []).filter(item => item.id !== tag.id).map(item => item.name))} disabled={savingTags} aria-label={`移除标签 ${tag.name}`}><X size={12} /></button> : null}
              </span>
            ))}
            {(chunk.tags || []).length === 0 ? <span className="chunk-tags-empty">暂无关联标签</span> : null}
          </div>
          {canWrite ? (
            <form className="chunk-tag-input" onSubmit={event => {
              event.preventDefault()
              const value = tagInput.trim()
              if (!value || (chunk.tags || []).some(tag => tag.name.localeCompare(value, 'zh-CN', { sensitivity: 'accent' }) === 0)) return
              updateTags([...(chunk.tags || []).map(tag => tag.name), value])
            }}>
              <label className="sr-only" htmlFor={`chunk-tag-input-${chunk.chunk_id}`}>添加关联标签</label>
              <input id={`chunk-tag-input-${chunk.chunk_id}`} value={tagInput} onChange={event => setTagInput(event.target.value)} list="knowledge-tag-suggestions" maxLength={32} placeholder="输入或选择标签后按回车" disabled={savingTags || (chunk.tags || []).length >= 8} />
              <button type="submit" className="btn-secondary" disabled={savingTags || !tagInput.trim() || (chunk.tags || []).length >= 8}><Tag size={14} aria-hidden="true" />添加</button>
            </form>
          ) : null}
          <datalist id="knowledge-tag-suggestions">
            {knownTags.map(tag => <option key={tag.id} value={tag.name} />)}
          </datalist>
        </section>

        {typeMeta || chunk.is_multimodal ? (
          <section className="chunk-media-section" aria-label="多模态信息">
            <MediaPreview chunk={chunk} type={type} />
            <dl className="chunk-media-meta">
              <div><dt>类型</dt><dd>{typeMeta?.label || '多模态内容'}</dd></div>
              {chunk.modal_entity_name ? <div><dt>名称</dt><dd>{chunk.modal_entity_name}</dd></div> : null}
              {chunk.page_idx != null ? <div><dt>页码</dt><dd>第 {chunk.page_idx} 页</dd></div> : null}
              {chunk.media_path ? <div><dt>文件</dt><dd title={chunk.media_path}>{chunk.media_path.split(/[/\\]/).pop()}</dd></div> : null}
            </dl>
          </section>
        ) : null}

        <section className="chunk-detail-content-section" aria-labelledby="chunk-detail-content-heading">
          <div className="chunk-detail-content-heading">
            <h2 id="chunk-detail-content-heading">切块正文</h2>
            <span>{formatNumber(String(chunk.content || '').length)} 字符</span>
          </div>
          {isEditing ? (
            <div className="chunk-editor">
              <label htmlFor={`chunk-editor-${chunk.chunk_id}`}>正文内容</label>
              <textarea id={`chunk-editor-${chunk.chunk_id}`} value={editValue} maxLength={MAX_CONTENT_LENGTH} disabled={saving} onChange={event => setEditValue(event.target.value)} rows={18} autoFocus />
              <div className="chunk-editor-footer">
                <span className={editValue.length >= MAX_CONTENT_LENGTH ? 'is-limit' : ''}>{formatNumber(editValue.length)} / {formatNumber(MAX_CONTENT_LENGTH)} 字符</span>
                <div className="chunk-action-group">
                  <button type="button" className="btn-secondary" onClick={() => setEditMode(false)} disabled={saving}><X size={15} aria-hidden="true" />取消</button>
                  <button type="button" className="btn-primary" onClick={saveChunk} disabled={saving || !editValue.trim() || editValue.length > MAX_CONTENT_LENGTH}>
                    {saving ? <Loader2 className="animate-spin" size={15} /> : <Save size={15} />}
                    {saving ? '保存中' : '保存修改'}
                  </button>
                </div>
              </div>
              {!editValue.trim() ? <p className="chunk-field-error" role="alert">切块正文不能为空。</p> : null}
            </div>
          ) : <pre className="chunk-detail-content">{chunk.content || '(空内容)'}</pre>}
        </section>
        {canWrite && total <= 1 ? <p className="chunk-last-warning">最后一个切块不能单独删除。如不再需要此内容，请返回知识库删除整篇文档。</p> : null}
      </section>

      <UserDialogConfirmation
        isOpen={deleteOpen}
        title="确认永久删除此切块"
        description="删除后会立即从文本与向量检索中移除，且无法撤销。"
        confirmLabel={deleting ? '删除中' : '永久删除'}
        cancelLabel="取消"
        onConfirm={deleteChunk}
        onCancel={() => !deleting && setDeleteOpen(false)}
        danger
        confirmDisabled={deleting}
        closeDisabled={deleting}
        lockScroll
      />

      {toast ? <div className={`chunk-page-toast ${toast.type}`} role="status" aria-live="polite">{toast.message}</div> : null}
    </div>
  )
}
