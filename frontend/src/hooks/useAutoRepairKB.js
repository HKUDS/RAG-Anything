import { useState, useEffect, useCallback } from 'react'
import { api } from '../utils/api'

/**
 * Shared hook for autorepair KB selection.
 * Encapsulates localStorage persistence, API-driven KB list loading,
 * response format normalization, and KB creation.
 *
 * Used by: AutoRepairDashboardPage, AutoRepairAgentPage, AutoRepairKnowledgePage
 */
export function useAutoRepairKB() {
  const [arKb, setArKbRaw] = useState(() => {
    try {
      let stored = localStorage.getItem('autorepair_kb')
      // Migrate legacy key + value from manufacturing era
      if (!stored) {
        const legacy = localStorage.getItem('mfg_kb')
        if (legacy && legacy !== 'default') {
          stored = (legacy === 'manufacturing') ? 'autorepair' : legacy
          localStorage.setItem('autorepair_kb', stored)
          localStorage.removeItem('mfg_kb')
        }
      }
      // Handle legacy value in existing autorepair_kb key
      if (stored === 'manufacturing') {
        stored = 'autorepair'
        localStorage.setItem('autorepair_kb', 'autorepair')
      }
      return (stored && stored !== 'default') ? stored : 'autorepair'
    } catch {
      return 'autorepair'
    }
  })
  const [kbList, setKbList] = useState([])
  const [kbLoading, setKbLoading] = useState(true)
  const [kbError, setKbError] = useState(null)
  const [creating, setCreating] = useState(false)

  const setArKb = (kb) => {
    setArKbRaw(kb)
    try {
      localStorage.setItem('autorepair_kb', kb)
    } catch {
      // localStorage full or unavailable — non-critical
    }
  }

  const refreshKbList = useCallback(() => {
    setKbLoading(true)
    setKbError(null)
    return api.get('/autorepair/kb-list')
      .then((r) => {
        let items = []  // {name, label}[]
        if (Array.isArray(r)) {
          items = r.map((k) => ({ name: k.name || k.label, label: k.label || k.name })).filter(x => x.name)
        } else if (r && typeof r === 'object') {
          items = (r.knowledge_bases || []).map((k) => ({ name: k.name, label: k.label || k.name })).filter(x => x.name)
        }
        if (!items.length) items = [{ name: 'autorepair', label: '汽修知识库' }]
        const names = items.map(i => i.name)
        setKbList(items)
        // If the stored KB is no longer in the autorepair list
        // (e.g. old localStorage value pointing to a general KB),
        // automatically fall back to the first available autorepair KB.
        setArKbRaw(prev => {
          if (!names.includes(prev)) {
            const fallback = items[0].name
            try { localStorage.setItem('autorepair_kb', fallback) } catch { /* non-critical */ }
            return fallback
          }
          return prev
        })
        return items
      })
      .catch((e) => {
        console.warn('[useAutoRepairKB] Failed to load KB list:', e.message)
        setKbError(e.message || 'Failed to load KB list')
        setKbList([{ name: 'autorepair', label: '汽修知识库' }])
        return [{ name: 'autorepair', label: '汽修知识库' }]
      })
      .finally(() => setKbLoading(false))
  }, [])

  /** Create a new autorepair-domain KB and refresh the list. */
  const createArKb = useCallback(async (kbName, label) => {
    setCreating(true)
    try {
      const params = new URLSearchParams({ kb_name: kbName, domain: 'autorepair' })
      if (label) params.set('label', label)
      await api.post(`/kb/create?${params.toString()}`)
      const items = await refreshKbList()
      // Auto-select the newly created KB
      if (items.some(i => i.name === kbName)) {
        setArKb(kbName)
      }
      return { success: true }
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message || '创建失败'
      return { success: false, error: msg }
    } finally {
      setCreating(false)
    }
  }, [refreshKbList, setArKb])

  // Initial load
  useEffect(() => {
    refreshKbList()
  }, [refreshKbList])

  return { arKb, setArKb, kbList, kbLoading, kbError, creating, createArKb, refreshKbList }
}
