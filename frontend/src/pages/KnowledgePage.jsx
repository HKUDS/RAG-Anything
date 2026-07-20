import { useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo } from 'react'
import { Plus, Layers, Trash2, Clock, Database, FileText, CircleDot, X, Search, UserRound, ListFilter, ChevronDown, Check, ArrowDownNarrowWide, ArrowUpNarrowWide } from 'lucide-react'
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { api, setCurrentKB, getCurrentKB } from '../utils/api'
import Pagination from '../components/Pagination'
import { sortKnowledgeBases } from '../utils/kbSorting'

const KB_GRID_ROWS = 3
const FALLBACK_GRID_COLUMNS = 4
const FALLBACK_PAGE_SIZE = FALLBACK_GRID_COLUMNS * KB_GRID_ROWS
const KB_LIST_CACHE_KEY = 'raganything:kb-list-cache'
const KB_STATS_CACHE_KEY = 'raganything:kb-stats-cache'
const SORT_OPTIONS = [
  { value: 'updated', label: '更新时间', Icon: Clock },
  { value: 'entities', label: '实体数量', Icon: CircleDot },
  { value: 'documents', label: '文档数量', Icon: FileText },
]

function readCachedKBList() {
  if (typeof window === 'undefined') return []
  try {
    const raw = sessionStorage.getItem(KB_LIST_CACHE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeCachedKBList(kbs) {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.setItem(KB_LIST_CACHE_KEY, JSON.stringify(Array.isArray(kbs) ? kbs : []))
  } catch {
    // Ignore storage quota / privacy mode failures.
  }
}

function readCachedKBStats() {
  if (typeof window === 'undefined') return {}
  try {
    const raw = sessionStorage.getItem(KB_STATS_CACHE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function writeCachedKBStats(stats) {
  if (typeof window === 'undefined') return
  try {
    const persistedStats = Object.fromEntries(
      Object.entries(stats).filter(([, value]) => value?.unavailable !== true)
    )
    sessionStorage.setItem(KB_STATS_CACHE_KEY, JSON.stringify(persistedStats))
  } catch {
    // Ignore storage quota / privacy mode failures.
  }
}

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
function KBSelector({ kbs, kbStats, onSwitch, onDelete, deletingKB, gridRef, reserveRows = false }) {
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

  const formatDate = (iso) => {
    if (!iso) return ''
    try {
      const d = new Date(iso)
      if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
      return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
    } catch {
      return iso.slice(0, 10)
    }
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

        return (
          <motion.article
            key={kb.name}
            layout
            className="directory-card resource-card resource-card-kb group cursor-pointer"
          >
            <button
              type="button"
              className="resource-card-kb-hitarea"
              onClick={() => onSwitch(kb.name)}
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
                <span>更新 {formatDate(kb.last_content_updated_at || kb.created) || '暂无日期'}</span>
              </span>
              {kb.owner_username && (
                <span className="resource-card-kb-owner" title={`所有者：${kb.owner_username}`}>
                  <UserRound size={11} />
                  <span>@{kb.owner_username}</span>
                </span>
              )}
            </div>

            {kb.name !== 'default' && (
              <button
                type="button"
                onClick={(e) => handleDeleteClick(e, kb)}
                onKeyDown={e => e.stopPropagation()}
                className="resource-card-kb-delete absolute opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity rounded-lg text-ink-muted hover:text-rose-500 hover:bg-rose-50"
                title="删除知识库"
                aria-label={`删除 ${kb.label || kb.name}`}
              >
                <Trash2 size={13} />
              </button>
            )}
          </motion.article>
        )
      })}

      {/* 删除确认 */}
      <AnimatePresence>
        {showDelete && deleteTarget && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-sky-900/20"
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
  const initialCachedKBListRef = useRef(readCachedKBList())
  const initialCachedStatsRef = useRef(readCachedKBStats())
  const [kbs, setKBs] = useState(() => initialCachedKBListRef.current)
  const [kbsLoaded, setKbsLoaded] = useState(() => initialCachedKBListRef.current.length > 0)
  const [deletingKB, setDeletingKB] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [newKBName, setNewKBName] = useState('')
  const [toast, setToast] = useState(null)
  const [kbStats, setKbStats] = useState(() => initialCachedStatsRef.current)
  const [loadError, setLoadError] = useState(false)
  const [search, setSearch] = useState('')
  const [sortField, setSortField] = useState('updated')
  const [sortDirection, setSortDirection] = useState('desc')
  const [showSortMenu, setShowSortMenu] = useState(false)
  const [sortMenuPosition, setSortMenuPosition] = useState(null)
  const [sortMenuFocusIndex, setSortMenuFocusIndex] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(FALLBACK_PAGE_SIZE)
  const gridRef = useRef(null)
  const createInputRef = useRef()
  const sortControlRef = useRef(null)
  const sortTriggerRef = useRef(null)
  const sortMenuRef = useRef(null)
  const sortMenuItemRefs = useRef({})
  const sortValueRef = useRef(null)
  const sortMenuCloseTimeoutRef = useRef(null)
  const kbStatsRef = useRef({})
  const staleStatsRef = useRef(new Set(Object.keys(initialCachedStatsRef.current)))
  const pendingStatsRef = useRef(new Set())
  const statsGenRef = useRef(0)
  const [statsReloadKey, setStatsReloadKey] = useState(0)
  const prefersReducedMotion = useReducedMotion()

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
    writeCachedKBStats(kbStats)
  }, [kbStats])

  useEffect(() => {
    writeCachedKBList(kbs)
  }, [kbs])

  useEffect(() => { if (showCreate && createInputRef.current) createInputRef.current.focus() }, [showCreate])

  useLayoutEffect(() => {
    const grid = gridRef.current
    if (!grid) return undefined

    let frame = 0
    const updatePageSize = () => {
      if (frame) cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const templateColumns = window.getComputedStyle(grid).gridTemplateColumns
        const columns = templateColumns && templateColumns !== 'none'
          ? templateColumns.split(' ').filter(Boolean).length
          : 1

        setPageSize(Math.max(1, columns) * KB_GRID_ROWS)
      })
    }

    updatePageSize()

    const resizeObserver = typeof ResizeObserver !== 'undefined'
      ? new ResizeObserver(updatePageSize)
      : null

    resizeObserver?.observe(grid)
    window.addEventListener('resize', updatePageSize)

    return () => {
      if (frame) cancelAnimationFrame(frame)
      resizeObserver?.disconnect()
      window.removeEventListener('resize', updatePageSize)
    }
  }, [])

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

  // 跳转到知识库详情页
  const switchKB = useCallback((name) => {
    setCurrentKB(name)
    navigate(`/knowledge/${name}`)
  }, [navigate])

  // 创建知识库
  const createKB = useCallback(async (name) => {
    try {
      await api.createKB(name, name)
      showToast(`知识库 "${name}" 创建成功`, 'success')
      setNewKBName('')
      setShowCreate(false)
      loadKBs()
    } catch (e) {
      showToast('创建失败: ' + e.message, 'error')
    }
  }, [loadKBs])

  const openCreateModal = useCallback(() => {
    setShowCreate(true)
  }, [])

  const closeCreateModal = useCallback(() => {
    setShowCreate(false)
    setNewKBName('')
  }, [])

  const handleCreateKB = useCallback(() => {
    const name = newKBName.trim()
    if (!name) return
    createKB(name)
  }, [createKB, newKBName])

  // 删除知识库
  const deleteKB = useCallback(async (name, onDone) => {
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

  const totalPages = Math.max(1, Math.ceil(sortedKBs.length / pageSize))
  const currentPage = Math.min(page, totalPages)
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

  const activeSortOption = SORT_OPTIONS.find(option => option.value === sortField) || SORT_OPTIONS[0]
  const ActiveSortIcon = activeSortOption.Icon
  const directionLabel = sortDirection === 'asc' ? '当前为升序，切换为降序' : '当前为降序，切换为升序'
  const sortDirectionDescription = sortField === 'updated'
    ? (sortDirection === 'asc' ? '最早优先' : '最新优先')
    : (sortDirection === 'asc' ? '从少到多' : '从多到少')

  const clearSortMenuCloseTimeout = useCallback(() => {
    if (sortMenuCloseTimeoutRef.current === null) return
    window.clearTimeout(sortMenuCloseTimeoutRef.current)
    sortMenuCloseTimeoutRef.current = null
  }, [])

  const closeSortMenu = useCallback((restoreTriggerFocus = false) => {
    clearSortMenuCloseTimeout()
    setShowSortMenu(false)
    setSortMenuPosition(null)
    if (restoreTriggerFocus) {
      window.requestAnimationFrame(() => sortTriggerRef.current?.focus())
    }
  }, [clearSortMenuCloseTimeout])

  const scheduleSortMenuClose = useCallback(() => {
    clearSortMenuCloseTimeout()
    sortMenuCloseTimeoutRef.current = window.setTimeout(() => {
      sortMenuCloseTimeoutRef.current = null
      closeSortMenu()
    }, 200)
  }, [clearSortMenuCloseTimeout, closeSortMenu])

  const openSortMenu = useCallback(() => {
    clearSortMenuCloseTimeout()
    const selectedIndex = Math.max(0, SORT_OPTIONS.findIndex(option => option.value === sortField))
    setSortMenuFocusIndex(selectedIndex)
    setShowSortMenu(true)
  }, [clearSortMenuCloseTimeout, sortField])

  useEffect(() => () => {
    clearSortMenuCloseTimeout()
  }, [clearSortMenuCloseTimeout])

  const focusSortMenuOption = useCallback((index) => {
    const normalizedIndex = (index + SORT_OPTIONS.length) % SORT_OPTIONS.length
    setSortMenuFocusIndex(normalizedIndex)
    window.requestAnimationFrame(() => sortMenuItemRefs.current[normalizedIndex]?.focus())
  }, [])

  useLayoutEffect(() => {
    if (!showSortMenu || !sortControlRef.current || !sortMenuRef.current) return undefined

    const updateSortMenuPosition = () => {
      const controlRect = sortControlRef.current.getBoundingClientRect()
      const menuRect = sortMenuRef.current.getBoundingClientRect()
      const viewportMargin = 12
      const left = Math.max(
        viewportMargin,
        Math.min(controlRect.right - menuRect.width, window.innerWidth - menuRect.width - viewportMargin)
      )
      const belowTop = controlRect.bottom + 8
      const top = belowTop + menuRect.height <= window.innerHeight - viewportMargin
        ? belowTop
        : Math.max(viewportMargin, controlRect.top - menuRect.height - 8)

      setSortMenuPosition({ top, left })
    }

    updateSortMenuPosition()
    window.addEventListener('resize', updateSortMenuPosition)
    window.addEventListener('scroll', updateSortMenuPosition, true)
    window.requestAnimationFrame(() => sortMenuItemRefs.current[sortMenuFocusIndex]?.focus())

    return () => {
      window.removeEventListener('resize', updateSortMenuPosition)
      window.removeEventListener('scroll', updateSortMenuPosition, true)
    }
  }, [showSortMenu, sortMenuFocusIndex])

  useEffect(() => {
    if (!showSortMenu) return undefined

    const isInsideSortControl = (target) => (
      sortControlRef.current?.contains(target) || sortMenuRef.current?.contains(target)
    )
    const closeOnOutsidePointer = (event) => {
      if (!isInsideSortControl(event.target)) closeSortMenu()
    }
    const closeOnFocusAway = (event) => {
      if (!isInsideSortControl(event.target)) closeSortMenu()
    }
    const closeOnEscape = (event) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      closeSortMenu(true)
    }

    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('focusin', closeOnFocusAway)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      document.removeEventListener('focusin', closeOnFocusAway)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [closeSortMenu, showSortMenu])

  const selectSortField = (field) => {
    setSortField(field)
    setPage(1)
    closeSortMenu(true)
  }

  const handleSortMenuKeyDown = (event, index) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusSortMenuOption(index + 1)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      focusSortMenuOption(index - 1)
    } else if (event.key === 'Home') {
      event.preventDefault()
      focusSortMenuOption(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      focusSortMenuOption(SORT_OPTIONS.length - 1)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      closeSortMenu(true)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      selectSortField(SORT_OPTIONS[index].value)
    }
  }

  const sortMenu = typeof document === 'undefined' ? null : createPortal(
    <AnimatePresence>
      {showSortMenu && (
        <motion.div
          ref={sortMenuRef}
          id="kb-sort-options"
          className="resource-sort-menu"
          initial={prefersReducedMotion ? false : { opacity: 0, y: -4, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={prefersReducedMotion ? undefined : { opacity: 0, y: -4, scale: 0.98 }}
          transition={{ duration: prefersReducedMotion ? 0 : 0.16, ease: 'easeOut' }}
          style={{
            top: sortMenuPosition?.top ?? 0,
            left: sortMenuPosition?.left ?? 0,
            visibility: sortMenuPosition ? 'visible' : 'hidden',
          }}
          onMouseEnter={clearSortMenuCloseTimeout}
          onMouseLeave={scheduleSortMenuClose}
          role="menu"
          aria-label="选择知识库排序依据"
        >
          {SORT_OPTIONS.map(({ value, label, Icon }, index) => {
            const isSelected = sortField === value
            return (
              <button
                key={value}
                ref={element => { sortMenuItemRefs.current[index] = element }}
                type="button"
                role="menuitemradio"
                className={`resource-sort-option${isSelected ? ' is-selected' : ''}`}
                onClick={() => selectSortField(value)}
                onKeyDown={event => handleSortMenuKeyDown(event, index)}
                onFocus={() => setSortMenuFocusIndex(index)}
                aria-checked={isSelected}
                tabIndex={index === sortMenuFocusIndex ? 0 : -1}
              >
                <Icon size={16} aria-hidden="true" />
                <span>{label}</span>
                {isSelected && <Check size={16} className="resource-sort-option-check" aria-hidden="true" />}
              </button>
            )
          })}
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  )

  return (
    <div className="resource-page resource-page-kbs">
      {/* 页面头部 */}
      <div className="page-header page-header-divider resource-page-header">
        <div>
          <h2 className="page-title">知识库</h2>
          <p className="page-subtitle">选择一个知识库查看文档、图谱和实体</p>
        </div>
        <button onClick={openCreateModal} className="btn-primary">
          <Plus size={16} /> 新建知识库
        </button>
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
            <div ref={sortControlRef} className="resource-sort-controls" role="group" aria-label="知识库排序">
              <button
                ref={sortTriggerRef}
                type="button"
                className="resource-sort-trigger"
                onClick={() => {
                  if (showSortMenu) closeSortMenu()
                  else openSortMenu()
                }}
                aria-expanded={showSortMenu}
                aria-controls="kb-sort-options"
                aria-haspopup="menu"
                aria-label={`排序依据：${activeSortOption.label}。当前排序方式：${sortDirectionDescription}`}
              >
                <ListFilter size={16} aria-hidden="true" />
                <span className="resource-sort-prefix">排序</span>
                <span
                  ref={sortValueRef}
                  className="resource-sort-value"
                  onMouseEnter={openSortMenu}
                  onMouseLeave={scheduleSortMenuClose}
                >
                  <ActiveSortIcon size={15} aria-hidden="true" />
                  {activeSortOption.label}
                </span>
                <ChevronDown size={16} className={`resource-sort-chevron${showSortMenu ? ' is-open' : ''}`} aria-hidden="true" />
              </button>
              <span className="resource-sort-divider" aria-hidden="true" />
              <button
                type="button"
                className="resource-sort-direction"
                onClick={() => {
                  setSortDirection(direction => direction === 'asc' ? 'desc' : 'asc')
                  setPage(1)
                  closeSortMenu()
                }}
                title={directionLabel}
                aria-label={directionLabel}
                aria-pressed={sortDirection === 'asc'}
              >
                {sortDirection === 'asc'
                  ? <ArrowUpNarrowWide size={17} aria-hidden="true" />
                  : <ArrowDownNarrowWide size={17} aria-hidden="true" />}
              </button>
            </div>
            {sortMenu}
            <div className="resource-count">
              共 {kbs.length} 个知识库
              {normalizedSearch ? `，匹配到 ${filteredKBs.length} 个结果` : ''}
            </div>
          </div>
        </div>

        <KBSelector
          kbs={paginatedKBs}
          kbStats={kbStats}
          onSwitch={switchKB}
          onDelete={deleteKB}
          deletingKB={deletingKB}
          gridRef={gridRef}
          reserveRows={paginatedKBs.length > 0}
        />

        {sortedKBs.length > 0 && (
          <Pagination page={currentPage} totalPages={totalPages} onPageChange={setPage} className="resource-pagination resource-pagination-kbs" />
        )}

        {loadError && kbs.length > 0 && (
          <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <p>知识库列表刷新失败，当前显示的是缓存数据。</p>
            <button type="button" onClick={loadKBs} className="btn-secondary text-sm">
              重试
            </button>
          </div>
        )}

        {/* 尚未加载知识库时的空状态 */}
        {kbsLoaded && kbs.length === 0 && !loadError && (
          <div className="empty-state resource-empty-state">
            <Layers size={48} className="mx-auto mb-4 text-cloud-400" />
            <p className="text-ink-muted text-sm mb-2">还没有知识库</p>
            <button onClick={openCreateModal} className="btn-primary text-sm">
              <Plus size={16} /> 新建知识库
            </button>
          </div>
        )}

        {kbsLoaded && kbs.length === 0 && loadError && (
          <div className="empty-state resource-empty-state">
            <Database size={48} className="mx-auto mb-4 text-cloud-400" />
            <p className="text-ink-primary text-sm font-medium mb-2">知识库列表加载失败</p>
            <p className="text-ink-muted text-sm mb-4">请稍后重试，或确认后端服务已经正常启动。</p>
            <button type="button" onClick={loadKBs} className="btn-secondary text-sm">
              重新加载
            </button>
          </div>
        )}

        {kbs.length > 0 && filteredKBs.length === 0 && (
          <div className="empty-state resource-empty-state">
            <Search size={40} className="mx-auto mb-4 text-cloud-400" />
            <p className="text-ink-primary text-sm font-medium mb-2">没有找到匹配的知识库</p>
            <p className="text-ink-muted text-sm">试试搜索名称、拥有者，或者文档与实体数量</p>
          </div>
        )}
      </section>

      {/* 创建知识库弹窗 */}
      <AnimatePresence>
        {showCreate && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-sky-900/20"
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
