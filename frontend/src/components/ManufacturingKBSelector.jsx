import { useState, useRef, useEffect } from 'react'
import { Plus, Loader2, AlertCircle } from 'lucide-react'

/**
 * Shared KB selector for manufacturing pages.
 *
 * Renders a <select> dropdown for manufacturing-domain KBs, a "+" button
 * to create a new sub-domain KB, and an inline creation form.
 *
 * Props:
 *   mfgKb       - currently selected KB name
 *   kbList      - array of available KB names
 *   loading     - whether the KB list is loading
 *   creating    - whether a create operation is in progress
 *   onChange    - called with the new KB name on selection change
 *   onCreate    - called with (kbName, label) to create a new manufacturing KB;
 *                 should return { success: bool, error?: string }
 */
export default function ManufacturingKBSelector({
  mfgKb,
  kbList,
  loading,
  creating,
  onChange,
  onCreate,
}) {
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [createError, setCreateError] = useState(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (showCreate && inputRef.current) inputRef.current.focus()
  }, [showCreate])

  const handleCreate = async () => {
    const name = newName.trim()
    if (!name) return
    setCreateError(null)
    const result = await onCreate(name, name)
    if (result.success) {
      setNewName('')
      setShowCreate(false)
    } else {
      setCreateError(result.error || '创建失败')
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleCreate()
    if (e.key === 'Escape') {
      setShowCreate(false)
      setNewName('')
    }
  }

  return (
    <div className="relative flex items-center gap-2">
      <select
        value={mfgKb}
        disabled={loading}
        onChange={e => onChange(e.target.value)}
        className="px-3 py-1.5 rounded-lg border border-warm-200 text-sm bg-white text-warm-700 cursor-pointer disabled:opacity-50"
      >
        {kbList.length === 0 && <option value="manufacturing">KB: manufacturing</option>}
        {kbList.map(k => <option key={k} value={k}>KB: {k}</option>)}
      </select>

      <button
        onClick={() => { setShowCreate(!showCreate); setCreateError(null) }}
        disabled={creating}
        className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs border border-warm-200 text-warm-500 hover:text-warm-700 hover:bg-warm-50 transition-colors disabled:opacity-50"
        title="新建制造领域知识库"
      >
        {creating ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
        <span className="hidden sm:inline">新建</span>
      </button>

      {/* Inline create form */}
      {showCreate && (
        <div className="absolute top-full right-0 mt-2 w-64 bg-white border border-warm-200 rounded-xl shadow-lg p-4 z-50">
          <p className="text-sm font-medium text-warm-800 mb-3">新建制造领域知识库</p>
          <div className="space-y-2">
            <input
              ref={inputRef}
              type="text"
              value={newName}
              onChange={e => { setNewName(e.target.value); setCreateError(null) }}
              onKeyDown={handleKeyDown}
              placeholder="输入子领域名称，如：焊接工艺"
              className="w-full px-3 py-2 rounded-lg border border-warm-200 text-sm text-warm-800 placeholder-warm-400 focus:outline-none focus:border-coral-400 transition-colors"
              maxLength={40}
            />
            {createError && (
              <p className="flex items-center gap-1 text-xs text-rose-500">
                <AlertCircle size={12} /> {createError}
              </p>
            )}
            <div className="flex gap-2 pt-1">
              <button
                onClick={handleCreate}
                disabled={!newName.trim() || creating}
                className="flex-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-coral-500 text-white hover:bg-coral-600 disabled:opacity-40 transition-colors"
              >
                {creating ? '创建中…' : '确认创建'}
              </button>
              <button
                onClick={() => { setShowCreate(false); setNewName('') }}
                className="px-3 py-1.5 rounded-lg text-xs border border-warm-200 text-warm-500 hover:bg-warm-50 transition-colors"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
