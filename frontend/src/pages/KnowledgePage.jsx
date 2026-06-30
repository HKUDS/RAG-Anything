import { useState, useEffect, useRef, useCallback } from 'react'
import { Plus, Layers, Trash2, Clock, Database, FileText, Hash } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { api, setCurrentKB, getCurrentKB } from '../utils/api'

// ====================== KB Selector (Card Grid) ======================
function KBSelector({ kbs, activeKB, kbStats, onSwitch, onCreate, onDelete, deletingKB }) {
  const [showCreate, setShowCreate] = useState(false)
  const [showDelete, setShowDelete] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [newKBName, setNewKBName] = useState('')
  const inputRef = useRef()

  useEffect(() => { if (showCreate && inputRef.current) inputRef.current.focus() }, [showCreate])

  const handleCreate = () => {
    if (!newKBName.trim()) return
    onCreate(newKBName.trim())
    setNewKBName('')
    setShowCreate(false)
  }

  const handleDeleteClick = (e, kb) => {
    e.stopPropagation()
    setDeleteTarget(kb)
    setShowDelete(true)
  }

  const formatDate = (iso) => {
    if (!iso) return ''
    try {
      const d = new Date(iso)
      return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
    } catch { return iso.slice(0, 10) }
  }

  return (
    <div className="space-y-4">
      {/* KB Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {kbs.map(kb => {
          const isActive = kb.name === activeKB
          const stats = kbStats[kb.name]
          return (
            <motion.button
              key={kb.name}
              layout
              onClick={() => onSwitch(kb.name)}
              className={`relative text-left group rounded-xl p-5 transition-all duration-200 border cursor-pointer
                ${isActive
                  ? 'bg-sky-50 border-sky-400 shadow-cloud-sm ring-1 ring-sky-400/40'
                  : 'bg-white border-cloud-200 shadow-cloud-sm hover:shadow-cloud-md hover:border-sky-300 hover:-translate-y-0.5'
                }`}
            >
              {/* Active indicator */}
              {isActive && (
                <span className="absolute top-3 right-3 flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-sky-500" />
                </span>
              )}

              {/* Icon */}
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-3.5 transition-colors
                ${isActive ? 'bg-sky-200/60 text-sky-600' : 'bg-cloud-200 text-ink-muted group-hover:bg-sky-100 group-hover:text-sky-500'}`}
              >
                <Database size={20} />
              </div>

              {/* Name */}
              <h3 className={`text-sm font-semibold mb-1 truncate pr-6 transition-colors
                ${isActive ? 'text-sky-700' : 'text-ink-primary group-hover:text-ink-primary'}`}
              >
                {kb.label || kb.name}
              </h3>
              <p className="text-2xs text-ink-muted mb-3 truncate">{kb.name}</p>

              {/* Stats preview */}
              <div className="flex items-center gap-4 text-2xs text-ink-muted mb-2">
                {stats !== undefined ? (
                  <>
                    <span className="flex items-center gap-1" title="文档数"><FileText size={10} />{stats.documents || 0}</span>
                    <span className="flex items-center gap-1" title="实体数"><Hash size={10} />{stats.entities || 0}</span>
                  </>
                ) : (
                  <span className="text-ink-muted/60">加载中…</span>
                )}
              </div>

              {/* Meta */}
              <div className="flex items-center gap-3 text-2xs text-ink-muted">
                {kb.created && <span className="flex items-center gap-1"><Clock size={10} />{formatDate(kb.created)}</span>}
                {kb.owner_username && <span className="truncate">@{kb.owner_username}</span>}
              </div>

              {/* Delete (non-default KBs only) — show on hover */}
              {kb.name !== 'default' && (
                <button
                  onClick={(e) => handleDeleteClick(e, kb)}
                  className="absolute bottom-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-lg text-ink-muted hover:text-rose-500 hover:bg-rose-50"
                  title="删除知识库"
                >
                  <Trash2 size={13} />
                </button>
              )}
            </motion.button>
          )
        })}

        {/* Create New KB Card */}
        <motion.button
          layout
          onClick={() => setShowCreate(!showCreate)}
          className="rounded-xl border-2 border-dashed border-cloud-300 hover:border-sky-300 bg-transparent hover:bg-sky-50/50 p-5 flex flex-col items-center justify-center gap-2.5 text-ink-muted hover:text-sky-600 transition-all duration-200 min-h-[185px] cursor-pointer"
        >
          <div className="w-10 h-10 rounded-xl bg-cloud-200 flex items-center justify-center transition-colors">
            <Plus size={20} />
          </div>
          <span className="text-sm font-medium">新建知识库</span>
        </motion.button>
      </div>

      {/* Create popover */}
      <AnimatePresence>
        {showCreate && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.95 }}
            className="card p-4 shadow-cloud-md max-w-sm"
          >
            <p className="text-sm font-medium text-ink-primary mb-3">新建知识库</p>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-ink-muted mb-1 block">名称</label>
                <input
                  ref={inputRef}
                  className="input-field text-sm"
                  placeholder="输入知识库名称…"
                  value={newKBName}
                  maxLength={64}
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

// ====================== MAIN PAGE ======================
export default function KnowledgePage() {
  const navigate = useNavigate()
  const [kbs, setKBs] = useState([])
  const [activeKB, setActiveKB] = useState(null)
  const [kbsLoaded, setKbsLoaded] = useState(false)
  const [deletingKB, setDeletingKB] = useState(false)
  const [toast, setToast] = useState(null)
  const [kbStats, setKbStats] = useState({})
  const genRef = useRef(0)

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
      } else if (r.active && kbList.some(kb => kb.name === r.active)) {
        setActiveKB(r.active)
        setCurrentKB(r.active)
      } else if (kbList.length > 0) {
        setActiveKB(kbList[0].name)
        setCurrentKB(kbList[0].name)
      }
      // Fetch stats for all KBs sequentially (avoids race on module-level currentKB)
      const gen = ++genRef.current
      const statsMap = {}
      const prevKB = getCurrentKB()
      for (const kb of kbList) {
        try {
          setCurrentKB(kb.name)
          const s = await api.getStats()
          if (gen === genRef.current) statsMap[kb.name] = s
        } catch { /* skip KBs that fail */ }
      }
      setCurrentKB(prevKB)
      if (gen === genRef.current) setKbStats(statsMap)
    }
    setKbsLoaded(true)
  }, [])

  useEffect(() => { loadKBs() }, [loadKBs])

  // Navigate to KB detail page
  const switchKB = useCallback((name) => {
    setActiveKB(name)
    setCurrentKB(name)
    navigate(`/knowledge/${name}`)
  }, [navigate])

  // Create KB
  const createKB = useCallback(async (name) => {
    try {
      await api.createKB(name, name)
      showToast(`知识库 "${name}" 创建成功`, 'success')
      loadKBs()
    } catch (e) { showToast('创建失败: ' + e.message, 'error') }
  }, [loadKBs])

  // Delete KB
  const deleteKB = useCallback(async (name, onDone) => {
    setDeletingKB(true)
    try {
      await api.deleteKB(name)
      showToast(`知识库 "${name}" 已删除`, 'success')
      onDone?.()
      loadKBs()
    } catch (e) { showToast('删除失败: ' + e.message, 'error') }
    setDeletingKB(false)
  }, [loadKBs])

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header page-header-divider">
        <div>
          <h2 className="page-title">📚 知识库</h2>
          <p className="page-subtitle">选择一个知识库查看文档、图谱和实体</p>
        </div>
      </div>

      {/* KB Cards Grid */}
      <KBSelector
        kbs={kbs}
        activeKB={activeKB}
        kbStats={kbStats}
        onSwitch={switchKB}
        onCreate={createKB}
        onDelete={deleteKB}
        deletingKB={deletingKB}
      />

      {/* Empty state when no KBs loaded yet */}
      {kbsLoaded && kbs.length === 0 && (
        <div className="py-16 text-center">
          <Layers size={48} className="mx-auto mb-4 text-cloud-400" />
          <p className="text-ink-muted text-sm mb-2">还没有知识库</p>
          <p className="text-ink-muted text-xs mb-4">点击「新建知识库」卡片开始</p>
        </div>
      )}

      {/* Toast */}
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
