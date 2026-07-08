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
      // 迁移制造场景时期遗留的键和值
      if (!stored) {
        const legacy = localStorage.getItem('mfg_kb')
        if (legacy && legacy !== 'default') {
          stored = (legacy === 'manufacturing') ? 'autorepair' : legacy
          localStorage.setItem('autorepair_kb', stored)
          localStorage.removeItem('mfg_kb')
        }
      }
      // 处理 autorepair_kb 中已有的历史值
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
      // 本地存储已满或不可用，不影响主流程
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
        // 如果已存储的知识库不再位于汽修知识库列表中
        // 例如旧本地存储值指向通用知识库，
        // 自动回退到第一个可用的汽修知识库。
        setArKbRaw(prev => {
          if (!names.includes(prev)) {
            const fallback = items[0].name
            try { localStorage.setItem('autorepair_kb', fallback) } catch { /* 非关键错误 */ }
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

  /** 创建新的汽修领域知识库并刷新列表。 */
  const createArKb = useCallback(async (kbName, label) => {
    setCreating(true)
    try {
      const params = new URLSearchParams({ kb_name: kbName, domain: 'autorepair' })
      if (label) params.set('label', label)
      await api.post(`/kb/create?${params.toString()}`)
      const items = await refreshKbList()
      // 自动选中新创建的知识库
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

  // 初始加载
  useEffect(() => {
    refreshKbList()
  }, [refreshKbList])

  return { arKb, setArKb, kbList, kbLoading, kbError, creating, createArKb, refreshKbList }
}
