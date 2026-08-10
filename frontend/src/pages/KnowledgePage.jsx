import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { Plus, Layers, Trash2, Clock, Database, FileText, CircleDot, X, Search, UserRound, Pencil } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { api, setCurrentKB, getCurrentKB } from '../utils/api'
import { useAuth } from '../context/AuthContext'
import Pagination from '../components/Pagination'
import ResourceSortControl from '../components/ResourceSortControl'
import KnowledgeBaseEditorDrawer from '../components/KnowledgeBaseEditorDrawer'
import { getKnowledgeBaseUpdateTimestamp, sortKnowledgeBases } from '../utils/kbSorting'
import { canEditKnowledgeBase } from '../utils/knowledgeBaseEditor'
import { clampPage, getStoredPageSize, getTotalPages, storePageSize } from '../utils/pagination'
import { formatDate } from '../utils/dateFormat'

const PAGE_SIZE_STORAGE_KEY = 'raganything:pagination:knowledge-bases'
const KB_GRID_ROWS = 3
const SORT_OPTIONS = [
  { value: 'updated', label: '更新时间', Icon: Clock, type: 'time' },
  { value: 'entities', label: '实体数量', Icon: CircleDot, type: 'number' },
  { value: 'documents', label: '文档数量', Icon: FileText, type: 'number' },
]

function areStatsEqual(a, b) {
  return Boolean(a) === Boolean(b)
    && Number(a?.documents || 0) === Number(b?.documents || 0)
    && Number(a?.entities || 0) === Number(b?.entities || 0)
    && Number(a?.relations || 0) === Number(b?.relations || 0)
    && Number(a?.chunks || 0) === Number(b?.chunks || 0)
    && (a?.unavailable === true) === (b?.unavailable === true)
}

function shouldReplaceStats(currentStats, incomingStats) {
  if (incomingStats === undefined) return false
  if (currentStats === undefined) return true
  if (incomingStats?.unavailable === true && currentStats?.unavailable !== true) return false
  return !areStatsEqual(currentStats, incomingStats)
}

// ====================== 知识库选择器（卡片网格） ======================
function KBSelector({ kbs, kbStats, onSwitch, onPrefetch, onDelete, onEdit, deletingKB, gridRef, reserveRows = false, canDelete = false }) {
  const [showDelete, setShowDelete] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const gridClassName = reserveRows
    ? 'resource-grid resource-grid-kbs resource-grid-kbs-fixed-rows'
    : 'resource-grid resource-grid-kbs'
  const gridStyle = reserveRows
    ? { '--kb-grid-rows': KB_GRID_ROWS, '--kb-grid-row-gaps': KB_GRID_ROWS - 1 }
    : undefined

  const handleDeleteClick = (e, kb) => {
    e.stopPropagation()
    setDeleteTarget(kb)
    setShowDelete(true)
  }

  const formatCount = (value) => {
    const n = Number(value || 0)
    return new Intl.NumberFormat('zh-CN').format(Number.isFinite(n) ? n : 0)
  }

  return (
    <div ref={gridRef} className={gridClassName} style={gridStyle}>
      {kbs.map(kb => {
        const stats = kbStats[kb.name]
        const documentCount = Number(stats?.documents || 0)
        const entityCount = Number(stats?.entities || 0)
        const hasStats = stats !== undefined
        const isUnavailable = stats?.unavailable === true
        const canEdit = canEditKnowledgeBase(kb)

        return (
          <article
            key={kb.name}
            className="directory-card resource-card resource-card-kb group cursor-pointer"
            onPointerEnter={event => {
              if (event.pointerType === 'mouse') onPrefetch(kb.name)
            }}
          >
            <button
              type="button"
              className="resource-card-kb-hitarea"
              onClick={() => onSwitch(kb.name)}
              onFocus={() => onPrefetch(kb.name)}
              aria-label={`打开知识库 ${kb.label || kb.name}`}
            />

            <div className="resource-card-kb-head">
              <div className="directory-icon resource-card-kb-icon">
                <Database size={18} />
              </div>
              <div className="resource-card-kb-copy">
                <h3 className="resource-card-kb-title text-ink-primary">
                  {kb.label || kb.name}
                </h3>

              </div>
            </div>

            <div className="resource-card-kb-metrics" aria-label="知识库统计">
              {hasStats && !isUnavailable ? (
                <>
                  <span className="resource-card-kb-metric" title={`文档数：${formatCount(documentCount)}`}>
                    <FileText size={13} />
                    <strong>{formatCount(documentCount)}</strong>
                    <small>文档</small>
                  </span>
                  <span className="resource-card-kb-metric" title={`实体数：${formatCount(entityCount)}`}>
                    <CircleDot size={13} />
                    <strong>{formatCount(entityCount)}</strong>
                    <small>实体</small>
                  </span>
                </>
              ) : isUnavailable ? (
                <span className="resource-card-kb-loading">统计暂不可用</span>
              ) : (
                <span className="resource-card-kb-loading">加载统计中…</span>
              )}
            </div>

            <div className="directory-footer resource-card-kb-footer text-2xs text-ink-muted">
              <span className="resource-card-kb-meta" title="更新时间">
                <Clock size={11} />
                <span>更新 {formatDate(getKnowledgeBaseUpdateTimestamp(kb)) || '暂无日期'}</span>
              </span>
              {kb.owner_username && (
                <span className="resource-card-kb-owner" title={`所有者：${kb.owner_username}`}>
                  <UserRound size={11} />
                  <span>@{kb.owner_username}</span>
                </span>
              )}
            </div>

            {canEdit && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onEdit(kb)
                }}
                onKeyDown={e => e.stopPropagation()}
                className="absolute right-2 top-2 z-10 inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-sky-50 hover:text-sky-700"
                title="编辑知识库"
                aria-label={`编辑 ${kb.label || kb.name}`}
              >
                <Pencil size={15} aria-hidden="true" />
              </button>
            )}

            {canDelete && kb.name !== 'default' && (
              <button
                type="button"
                onClick={(e) => handleDeleteClick(e, kb)}
                onKeyDown={e => e.stopPropagation()}
                disabled={deletingKB}
                className="resource-card-kb-delete absolute z-10 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity rounded-lg text-ink-muted hover:text-rose-500 hover:bg-rose-50"
                title="删除知识库"
                aria-label={`删除 ${kb.label || kb.name}`}
              >
                <Trash2 size={13} />
              </button>
            )}
          </article>
        )
      })}

      {/* 删除确认 */}
      <AnimatePresence>
        {showDelete && deleteTarget && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
            onClick={() => { setShowDelete(false); setDeleteTarget(null) }}
            role="dialog"
            aria-modal="true"
            aria-label="确认删除知识库"
          >
            <div className="card p-6 max-w-sm w-full m-4" onClick={e => e.stopPropagation()}>
              <Trash2 size={32} className="mx-auto mb-3 text-rose-500" />
              <p className="text-ink-primary font-medium text-center mb-1">确认删除知识库</p>
              <p className="text-sm text-ink-muted text-center mb-2">
                「{deleteTarget.label || deleteTarget.name}」
              </p>
              <p className="text-xs text-rose-500 text-center mb-4">将清除所有文档、实体和向量数据，不可恢复</p>
              <div className="flex gap-3 justify-center">
                <button className="btn-secondary text-sm" onClick={() => { setShowDelete(false); setDeleteTarget(null) }}>取消</button>
                <button
                  className="btn-danger text-sm"
                  disabled={deletingKB}
                  onClick={() => onDelete(deleteTarget.name, () => { setShowDelete(false); setDeleteTarget(null) })}
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

// ====================== 主页面 ======================
export default function KnowledgePage() {
  const navigate = useNavigate()
  const { hasPermission } = useAuth()
  const canCreateKB = hasPermission('kb:write')
  const canDeleteKB = hasPermission('kb:delete')
  const [kbs, setKBs] = useState([])
  const [kbsLoaded, setKbsLoaded] = useState(false)
  const [deletingKB, setDeletingKB] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [editingKB, setEditingKB] = useState(null)
  const [newKBName, setNewKBName] = useState('')
  const [toast, setToast] = useState(null)
  const [kbStats, setKbStats] = useState({})
  const [loadError, setLoadError] = useState(false)
  const [search, setSearch] = useState('')
  const [sortField, setSortField] = useState('updated')
  const [sortDirection, setSortDirection] = useState('desc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(() => getStoredPageSize(PAGE_SIZE_STORAGE_KEY))
  const gridRef = useRef(null)
  const createInputRef = useRef()
  const kbStatsRef = useRef({})
  const staleStatsRef = useRef(new Set())
  const pendingStatsRef = useRef(new Set())
  const statsGenRef = useRef(0)
  const [statsReloadKey, setStatsReloadKey] = useState(0)

  const loadStatsForKBs = useCallback(async (kbNames) => {
    const names = [...new Set((kbNames || []).filter(Boolean))]
    if (names.length === 0) return

    const pendingStats = pendingStatsRef.current
    const targetNames = names.filter(name => {
      if (pendingStats.has(name)) return false
      const currentStats = kbStatsRef.current[name]
      return currentStats === undefined
        || currentStats?.unavailable === true
        || staleStatsRef.current.has(name)
    })
    if (targetNames.length === 0) return

    const statsGen = statsGenRef.current
    targetNames.forEach(name => pendingStats.add(name))

    let statsMap = {}
    try {
      const response = await api.getStatsBatchForKBs(targetNames)
      statsMap = response?.stats || {}
    } catch {
      statsMap = {}
    } finally {
      targetNames.forEach(name => pendingStats.delete(name))
    }

    if (statsGen !== statsGenRef.current) return

    const resolvedStats = Object.fromEntries(
      targetNames.map(name => {
        const stats = statsMap[name]
        return [name, stats === undefined || stats.unavailable
          ? { documents: 0, entities: 0, relations: 0, chunks: 0, unavailable: true }
          : stats]
      })
    )

    targetNames.forEach(name => {
      if (resolvedStats[name]?.unavailable === true) {
        staleStatsRef.current.add(name)
      } else {
        staleStatsRef.current.delete(name)
      }
    })

    setKbStats(prev => {
      const next = { ...prev }
      let changed = false

      for (const name of targetNames) {
        const nextStats = resolvedStats[name]
        if (!shouldReplaceStats(next[name], nextStats)) continue
        next[name] = nextStats
        changed = true
      }

      return changed ? next : prev
    })
  }, [])

  useEffect(() => {
    kbStatsRef.current = kbStats
  }, [kbStats])

  useEffect(() => { if (showCreate && createInputRef.current) createInputRef.current.focus() }, [showCreate])

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  // 加载知识库列表
  const loadKBs = useCallback(async () => {
    try {
      const r = await api.listKBs()
      const kbList = r.knowledge_bases || []
      setKBs(kbList)
      setKbStats(prev => {
        const allowedNames = new Set(kbList.map(kb => kb.name))
        let changed = false
        const next = {}

        for (const [name, stats] of Object.entries(prev)) {
          if (!allowedNames.has(name)) {
            changed = true
            continue
          }
          next[name] = stats
        }

        for (const kb of kbList) {
          if (kb.stats === undefined) continue
          if (!shouldReplaceStats(next[kb.name], kb.stats)) continue
          next[kb.name] = kb.stats
          changed = true
        }

        return changed ? next : prev
      })
      kbStatsRef.current = Object.fromEntries(
        Object.entries(kbStatsRef.current).filter(([name]) => kbList.some(kb => kb.name === name))
      )
      for (const kb of kbList) {
        if (shouldReplaceStats(kbStatsRef.current[kb.name], kb.stats)) {
          kbStatsRef.current[kb.name] = kb.stats
        }
      }
      staleStatsRef.current = new Set(
        Object.keys(kbStatsRef.current).filter(name => {
          const matchedKB = kbList.find(kb => kb.name === name)
          return matchedKB && (
            matchedKB.stats === undefined
            || matchedKB.stats?.unavailable === true
          )
        })
      )
      pendingStatsRef.current.clear()
      statsGenRef.current += 1
      setStatsReloadKey(key => key + 1)
      setLoadError(false)
      const current = getCurrentKB()
      const currentExists = current && kbList.some(kb => kb.name === current)

      if (!currentExists) {
        if (r.active && kbList.some(kb => kb.name === r.active)) {
          setCurrentKB(r.active)
        } else if (kbList.length > 0) {
          setCurrentKB(kbList[0].name)
        }
      }
    } catch {
      setLoadError(true)
      showToast('知识库列表加载失败，请稍后重试', 'error')
    } finally {
      setKbsLoaded(true)
    }
  }, [])

  useEffect(() => { loadKBs() }, [loadKBs])

  const prefetchKB = useCallback((name) => {
    if (!name || globalThis.navigator?.connection?.saveData) return
    api.prefetchKnowledgeDetail(name).catch(() => {})
  }, [])

  // 跳转到知识库详情页：等待目标 KB 的文档与统计预取，避免详情首帧误报为空。
  const switchKB = useCallback((name) => {
    api.prefetchKnowledgeDetail(name).catch(() => {})
    setCurrentKB(name)
    navigate(`/knowledge/${encodeURIComponent(name)}`)
  }, [navigate])

  // 创建知识库
  const createKB = useCallback(async (name) => {
    if (!canCreateKB) return
    try {
      await api.createKB(name, name)
      showToast(`知识库 "${name}" 创建成功`, 'success')
      setNewKBName('')
      setShowCreate(false)
      loadKBs()
    } catch (e) {
      showToast('创建失败: ' + e.message, 'error')
    }
  }, [canCreateKB, loadKBs])

  const openCreateModal = useCallback(() => {
    if (!canCreateKB) return
    setShowCreate(true)
  }, [canCreateKB])

  const closeCreateModal = useCallback(() => {
    setShowCreate(false)
    setNewKBName('')
  }, [])

  const handleCreateKB = useCallback(() => {
    if (!canCreateKB) return
    const name = newKBName.trim()
    if (!name) return
    createKB(name)
  }, [canCreateKB, createKB, newKBName])

  // 删除知识库
  const deleteKB = useCallback(async (name, onDone) => {
    if (!canDeleteKB) return
    setDeletingKB(true)
    try {
      await api.deleteKB(name)
      showToast(`知识库 "${name}" 已删除`, 'success')
      onDone?.()
      loadKBs()
    } catch (e) {
      showToast('删除失败: ' + e.message, 'error')
    }
    setDeletingKB(false)
  }, [canDeleteKB, loadKBs])

  const handleEditorSaved = useCallback((updated) => {
    if (updated?.name) {
      setKBs((current) => current.map((kb) => kb.name === updated.name
        ? { ...kb, ...updated, label: updated.label || updated.display_name || kb.label }
        : kb))
    }
    loadKBs()
  }, [loadKBs])

  const normalizedSearch = search.trim().toLowerCase()
  const filteredKBs = useMemo(() => kbs.filter(kb => {
    if (!normalizedSearch) return true
    return [
      kb.name,
      kb.label,
      kb.owner_username,
    ].some(value => String(value || '').toLowerCase().includes(normalizedSearch))
  }), [kbs, normalizedSearch])
  const sortedKBs = useMemo(
    () => sortKnowledgeBases(filteredKBs, kbStats, sortField, sortDirection),
    [filteredKBs, kbStats, sortField, sortDirection]
  )
  const kbNamesKey = kbs.map(kb => kb.name).join('|')
  const needsAllStats = sortField === 'documents' || sortField === 'entities'

  useEffect(() => {
    if (!needsAllStats) return
    loadStatsForKBs(kbs.map(kb => kb.name))
  }, [kbNamesKey, kbs, loadStatsForKBs, needsAllStats])

  const totalPages = getTotalPages(sortedKBs.length, pageSize)
  const currentPage = clampPage(page, totalPages)
  const paginatedKBs = sortedKBs.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const paginatedKBNamesKey = paginatedKBs.map(kb => kb.name).join('|')

  useEffect(() => {
    loadStatsForKBs(paginatedKBs.map(kb => kb.name))
  }, [loadStatsForKBs, paginatedKBNamesKey, statsReloadKey])

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  const updatePageSize = value => {
    const next = storePageSize(PAGE_SIZE_STORAGE_KEY, value)
    setPageSize(next)
    setPage(1)
  }

  return (
    <div className="resource-page resource-page-kbs">
      {/* 页面头部 */}
      <div className="page-header page-header-divider resource-page-header">
        <div>
          <h2 className="page-title">知识库</h2>
          <p className="page-subtitle">选择一个知识库查看文档、图谱和实体</p>
        </div>
        {canCreateKB && (
          <button onClick={openCreateModal} className="btn-primary">
            <Plus size={16} /> 新建知识库
          </button>
        )}
      </div>

      <section className="resource-panel">
        <div className="resource-toolbar">
          <div className="relative w-full lg:max-w-md">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted pointer-events-none" />
            <input
              className="input-field w-full pl-10 pr-4 text-sm"
              placeholder="搜索知识库名称或拥有者"
              aria-label="搜索知识库名称或拥有者"
              value={search}
              onChange={e => {
                setSearch(e.target.value)
                setPage(1)
              }}
            />
          </div>
          <div className="resource-toolbar-actions">
            <ResourceSortControl
              sortOptions={SORT_OPTIONS}
              sortField={sortField}
              sortDirection={sortDirection}
              onSortFieldChange={field => {
                setSortField(field)
                setPage(1)
              }}
              onSortDirectionChange={direction => {
                setSortDirection(direction)
                setPage(1)
              }}
              menuId="kb-sort-options"
              ariaLabel="知识库排序"
            />
            <div className="resource-count">
              共 {kbs.length} 个知识库
              {normalizedSearch ? `，匹配到 ${filteredKBs.length} 个结果` : ''}
            </div>
          </div>
        </div>

        {!kbsLoaded ? (
          <div className="resource-grid resource-grid-kbs" aria-busy="true">
            {[1, 2, 3, 4].map(item => (
              <div key={item} className="directory-card resource-card resource-card-kb" aria-hidden="true">
                <div className="flex items-center gap-3">
                  <div className="directory-icon resource-card-kb-icon">
                    <div className="skeleton h-[18px] w-[18px]" />
                  </div>
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="skeleton h-4 w-2/3" />
                    <div className="skeleton h-3 w-1/3" />
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-3">
                  <div className="skeleton h-5 w-16" />
                  <div className="skeleton h-5 w-16" />
                </div>
                <div className="mt-4">
                  <div className="skeleton h-3 w-1/3" />
                </div>
              </div>
            ))}
          </div>
        ) : paginatedKBs.length > 0 ? (
          <KBSelector
            kbs={paginatedKBs}
            kbStats={kbStats}
            onSwitch={switchKB}
            onPrefetch={prefetchKB}
            onDelete={deleteKB}
            onEdit={setEditingKB}
            deletingKB={deletingKB}
            canDelete={canDeleteKB}
            gridRef={gridRef}
            reserveRows
          />
        ) : (
          <div className="empty-state resource-empty-state">
            {kbs.length === 0 && !loadError ? (
              <>
                <Layers size={48} className="mx-auto mb-4 text-cloud-400" />
                <p className="text-ink-muted text-sm mb-2">还没有知识库</p>
                {canCreateKB && (
                  <button onClick={openCreateModal} className="btn-primary text-sm">
                    <Plus size={16} /> 新建知识库
                  </button>
                )}
              </>
            ) : kbs.length === 0 && loadError ? (
              <>
                <Database size={48} className="mx-auto mb-4 text-cloud-400" />
                <p className="text-ink-primary text-sm font-medium mb-2">知识库列表加载失败</p>
                <p className="text-ink-muted text-sm mb-4">请稍后重试，或确认后端服务已经正常启动。</p>
                <button type="button" onClick={loadKBs} className="btn-secondary text-sm">
                  重新加载
                </button>
              </>
            ) : (
              <>
                <Search size={40} className="mx-auto mb-4 text-cloud-400" />
                <p className="text-ink-primary text-sm font-medium mb-2">没有找到匹配的知识库</p>
                <p className="text-ink-muted text-sm">试试搜索名称、拥有者，或者文档与实体数量</p>
              </>
            )}
          </div>
        )}

        {sortedKBs.length > 0 && (
          <Pagination
            page={currentPage}
            totalPages={totalPages}
            onPageChange={setPage}
            pageSize={pageSize}
            onPageSizeChange={updatePageSize}
            className="resource-pagination resource-pagination-kbs"
          />
        )}

        {loadError && kbs.length > 0 && (
          <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <p>知识库列表刷新失败，当前显示的是缓存数据。</p>
            <button type="button" onClick={loadKBs} className="btn-secondary text-sm">
              重试
            </button>
          </div>
        )}

      </section>

      <AnimatePresence>
        {editingKB && (
          <KnowledgeBaseEditorDrawer
            kb={editingKB}
            isOpen
            onRequestClose={() => setEditingKB(null)}
            onSaved={handleEditorSaved}
          />
        )}
      </AnimatePresence>

      {/* 创建知识库弹窗 */}
      <AnimatePresence>
        {showCreate && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
            onClick={closeCreateModal}
            role="dialog"
            aria-modal="true"
            aria-label="新建知识库"
          >
            <motion.div
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 16, scale: 0.96 }}
              transition={{ duration: 0.18 }}
              className="card p-6 max-w-sm w-full m-4"
              onClick={e => e.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-4 mb-5">
                <div>
                  <p className="text-base font-semibold text-ink-primary">新建知识库</p>
                  <p className="text-xs text-ink-muted mt-1">创建新的文档、实体与图谱空间</p>
                </div>
                <button
                  className="p-1.5 rounded-lg text-ink-muted hover:text-ink-primary hover:bg-cloud-200 transition-colors"
                  onClick={closeCreateModal}
                  aria-label="关闭"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="text-xs text-ink-muted mb-1.5 block">知识库名称</label>
                  <input
                    ref={createInputRef}
                    className="input-field text-sm w-full"
                    placeholder="输入知识库名称…"
                    value={newKBName}
                    maxLength={64}
                    onChange={e => setNewKBName(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') handleCreateKB()
                      if (e.key === 'Escape') closeCreateModal()
                    }}
                  />
                </div>
                <div className="flex gap-2 justify-end">
                  <button className="btn-secondary text-sm" onClick={closeCreateModal}>取消</button>
                  <button className="btn-primary text-sm" onClick={handleCreateKB} disabled={!newKBName.trim()}>创建</button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 提示消息 */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.95 }}
            role="status"
            aria-live="polite"
            className={`fixed bottom-6 right-6 px-5 py-3 rounded-2xl text-sm font-medium z-50 shadow-cloud-md ${
              toast.type === 'error' ? 'toast-error' : toast.type === 'success' ? 'toast-success' : 'toast-info'
            }`}
          >
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
