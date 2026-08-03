import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../utils/api'
import { useAuth } from '../context/AuthContext'
import { rejectAutoRepairKbSelection, resolveAutoRepairKbSelection } from '../utils/autoRepairKbSelection'

const STORAGE_KEY = 'autorepair_kb'
const LEGACY_STORAGE_KEY = 'mfg_kb'

function readStoredCandidate() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && stored !== 'default') return stored === 'manufacturing' ? 'autorepair' : stored
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY)
    if (legacy && legacy !== 'default') return legacy === 'manufacturing' ? 'autorepair' : legacy
  } catch { /* storage is optional */ }
  return ''
}

function persistSelection(value) {
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY)
    if (value) localStorage.setItem(STORAGE_KEY, value)
    else localStorage.removeItem(STORAGE_KEY)
  } catch { /* storage is optional */ }
}

export function useAutoRepairKB() {
  const [arKb, setArKbRaw] = useState('')
  const [kbList, setKbList] = useState([])
  const [kbLoading, setKbLoading] = useState(true)
  const [kbError, setKbError] = useState(null)
  const [creating, setCreating] = useState(false)
  const requestGeneration = useRef(0)
  const { hasPermission } = useAuth()
  const canCreateArKb = hasPermission('kb:write')

  const setArKb = useCallback((kb) => {
    const confirmed = kbList.some(item => item.name === kb) ? kb : ''
    setArKbRaw(confirmed)
    persistSelection(confirmed)
  }, [kbList])

  const refreshKbList = useCallback(async () => {
    const generation = ++requestGeneration.current
    setKbLoading(true)
    setKbError(null)
    try {
      const response = await api.get('/autorepair/kb-list')
      if (generation !== requestGeneration.current) return []
      const { items, selected } = resolveAutoRepairKbSelection(response, readStoredCandidate())
      setKbList(items)
      setArKbRaw(selected)
      persistSelection(selected)
      return items
    } catch (error) {
      if (generation !== requestGeneration.current) return []
      const failed = rejectAutoRepairKbSelection(error)
      console.warn('[useAutoRepairKB] Failed to load KB list:', failed.error)
      setKbError(failed.error)
      setKbList(failed.items)
      setArKbRaw(failed.selected)
      persistSelection('')
      return []
    } finally {
      if (generation === requestGeneration.current) setKbLoading(false)
    }
  }, [])

  const createArKb = useCallback(async (kbName, label) => {
    if (!canCreateArKb) return { success: false, error: '' }
    setCreating(true)
    try {
      const params = new URLSearchParams({ kb_name: kbName, domain: 'autorepair' })
      if (label) params.set('label', label)
      await api.post(`/kb/create?${params.toString()}`)
      const items = await refreshKbList()
      if (items.some(item => item.name === kbName)) {
        setArKbRaw(kbName)
        persistSelection(kbName)
      }
      return { success: true }
    } catch (error) {
      return { success: false, error: error?.response?.data?.detail || error.message || '创建失败' }
    } finally {
      setCreating(false)
    }
  }, [canCreateArKb, refreshKbList])

  useEffect(() => {
    refreshKbList()
    return () => { requestGeneration.current += 1 }
  }, [refreshKbList])

  return { arKb, setArKb, kbList, kbLoading, kbError, creating, canCreateArKb, createArKb, refreshKbList }
}
