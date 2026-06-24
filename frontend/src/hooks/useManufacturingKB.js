import { useState, useEffect, useCallback } from 'react'
import { api } from '../utils/api'

/**
 * Shared hook for manufacturing KB selection.
 * Encapsulates localStorage persistence, API-driven KB list loading,
 * response format normalization, and KB creation.
 *
 * Used by: ManufacturingDashboardPage, ManufacturingAgentPage, ManufacturingKnowledgePage
 */
export function useManufacturingKB() {
  const [mfgKb, setMfgKbRaw] = useState(() => {
    try {
      const stored = localStorage.getItem('mfg_kb')
      // Migrate: 'default' is a general-purpose KB, not a manufacturing KB.
      // Any other previously-valid-but-now-filtered KB name is caught by the
      // functional updater in refreshKbList.
      return (stored && stored !== 'default') ? stored : 'manufacturing'
    } catch {
      return 'manufacturing'
    }
  })
  const [kbList, setKbList] = useState([])
  const [kbLoading, setKbLoading] = useState(true)
  const [kbError, setKbError] = useState(null)
  const [creating, setCreating] = useState(false)

  const setMfgKb = (kb) => {
    setMfgKbRaw(kb)
    try {
      localStorage.setItem('mfg_kb', kb)
    } catch {
      // localStorage full or unavailable — non-critical
    }
  }

  const refreshKbList = useCallback(() => {
    setKbLoading(true)
    setKbError(null)
    return api.get('/manufacturing/kb-list')
      .then((r) => {
        let items = []  // {name, label}[]
        if (Array.isArray(r)) {
          items = r.map((k) => ({ name: k.name || k.label, label: k.label || k.name })).filter(x => x.name)
        } else if (r && typeof r === 'object') {
          items = (r.knowledge_bases || []).map((k) => ({ name: k.name, label: k.label || k.name })).filter(x => x.name)
        }
        if (!items.length) items = [{ name: 'manufacturing', label: '制造知识库' }]
        const names = items.map(i => i.name)
        setKbList(items)
        // If the stored KB is no longer in the manufacturing list
        // (e.g. old localStorage value pointing to a general KB),
        // automatically fall back to the first available manufacturing KB.
        setMfgKbRaw(prev => {
          if (!names.includes(prev)) {
            const fallback = items[0].name
            try { localStorage.setItem('mfg_kb', fallback) } catch { /* non-critical */ }
            return fallback
          }
          return prev
        })
        return items
      })
      .catch((e) => {
        console.warn('[useManufacturingKB] Failed to load KB list:', e.message)
        setKbError(e.message || 'Failed to load KB list')
        setKbList([{ name: 'manufacturing', label: '制造知识库' }])
        return [{ name: 'manufacturing', label: '制造知识库' }]
      })
      .finally(() => setKbLoading(false))
  }, [])

  /** Create a new manufacturing-domain KB and refresh the list. */
  const createMfgKb = useCallback(async (kbName, label) => {
    setCreating(true)
    try {
      const params = new URLSearchParams({ kb_name: kbName, domain: 'manufacturing' })
      if (label) params.set('label', label)
      await api.post(`/kb/create?${params.toString()}`)
      const items = await refreshKbList()
      // Auto-select the newly created KB
      if (items.some(i => i.name === kbName)) {
        setMfgKb(kbName)
      }
      return { success: true }
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message || '创建失败'
      return { success: false, error: msg }
    } finally {
      setCreating(false)
    }
  }, [refreshKbList, setMfgKb])

  // Initial load
  useEffect(() => {
    refreshKbList()
  }, [refreshKbList])

  return { mfgKb, setMfgKb, kbList, kbLoading, kbError, creating, createMfgKb, refreshKbList }
}
