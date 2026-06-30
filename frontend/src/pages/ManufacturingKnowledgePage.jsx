import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Search, Database, AlertTriangle, Wrench, BookOpen,
  GitBranch, ChevronRight, ArrowLeft, Tag, Layers, Filter, X, GitGraph, AlertCircle,
  Plus, Edit3, Trash2, Loader2
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '../utils/api'
import { useManufacturingKB } from '../hooks/useManufacturingKB'
import ManufacturingKBSelector from '../components/ManufacturingKBSelector'
import KnowledgeGraphD3 from '../components/KnowledgeGraphD3'

// Simple error boundary to prevent a single crash from blanking the entire page
class KnowledgeErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null } }
  static getDerivedStateFromError(error) { return { hasError: true, error } }
  componentDidCatch(error, info) { console.error('[KnowledgePage] Render error:', error, info) }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center py-24">
          <div className="text-center space-y-3 max-w-sm">
            <AlertCircle size={32} className="mx-auto text-rose-400" />
            <p className="text-sm font-medium text-ink-body">知识库组件加载异常</p>
            <p className="text-xs text-ink-muted">{this.state.error?.message || '未知错误'}</p>
            <button onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload() }}
              className="px-4 py-2 text-xs font-medium text-white bg-sky-500 rounded-lg hover:bg-sky-600 transition-colors">
              刷新页面
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

const TABS = [
  { key: 'graph', icon: GitGraph, label: '图谱可视化' },
  { key: 'nodes', icon: GitBranch, label: '节点列表' },
  { key: 'faults', icon: AlertTriangle, label: '故障案例库' },
  { key: 'process', icon: Wrench, label: '企业工艺库' },
]

const BADGE_COLORS = {
  high: 'badge-error', medium: 'badge-warning', low: 'badge-success',
  critical: 'badge-error',
}

const SEVERITY_LABELS = {
  low: '低', medium: '中', high: '高', critical: '紧急',
}

const SEVERITY_OPTIONS = [
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'critical', label: '紧急' },
]

export default function ManufacturingKnowledgePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [activeTab, setActiveTab] = useState('graph')
  const [kgNodes, setKgNodes] = useState([])
  const [kgEdges, setKgEdges] = useState([])
  const [kgSummary, setKgSummary] = useState(null)
  const [kgLoading, setKgLoading] = useState(false)
  const [kgError, setKgError] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [lineage, setLineage] = useState(null)
  const [faultResults, setFaultResults] = useState([])
  const [faultStats, setFaultStats] = useState(null)
  const [processCats, setProcessCats] = useState({})
  const [processResults, setProcessResults] = useState([])
  const [searchQ, setSearchQ] = useState('')
  const [loading, setLoading] = useState(false)
  // Fault case CRUD state
  const [faultModalOpen, setFaultModalOpen] = useState(false)
  const [editingFault, setEditingFault] = useState(null)
  const [faultForm, setFaultForm] = useState({})
  const [faultSaving, setFaultSaving] = useState(false)
  // Process document CRUD state
  const [processModalOpen, setProcessModalOpen] = useState(false)
  const [editingProcess, setEditingProcess] = useState(null)
  const [processForm, setProcessForm] = useState({})
  const [processSaving, setProcessSaving] = useState(false)
  // Detail view state
  const [viewingFault, setViewingFault] = useState(null)
  const [viewingProcess, setViewingProcess] = useState(null)
  const [processDetailLoading, setProcessDetailLoading] = useState(false)
  const [processDetail, setProcessDetail] = useState(null)
  const { mfgKb, setMfgKb, kbList, kbLoading, creating, createMfgKb } = useManufacturingKB()

  // Generation counter to cancel stale in-flight requests
  const genRef = useRef(0)

  // ---- KG Data Loading (unified) ----
  const loadGraph = useCallback(async () => {
    const gen = ++genRef.current
    setKgLoading(true)
    setKgError(null)
    try {
      const [sumRes, nodesRes, edgesRes] = await Promise.all([
        api.get(`/manufacturing/knowledge-graph/summary?kb=${mfgKb}`),
        api.get('/manufacturing/knowledge-graph/nodes', { params: { limit: 2000, kb: mfgKb } }),
        api.get('/manufacturing/knowledge-graph/edges', { params: { limit: 5000, kb: mfgKb } }),
      ])
      if (gen !== genRef.current) return // stale — newer request in flight
      setKgSummary(sumRes)
      setKgNodes(nodesRes?.nodes || [])
      setKgEdges(edgesRes?.edges || [])
    } catch (e) {
      if (gen !== genRef.current) return
      console.error('[KG] 加载知识图谱失败:', e)
      setKgError(e.message || '加载知识图谱数据失败')
    } finally {
      if (gen === genRef.current) setKgLoading(false)
    }
  }, [mfgKb])

  const loadFaults = useCallback(async () => {
    const gen = ++genRef.current
    setLoading(true)
    try {
      const [statsRes, searchRes] = await Promise.all([
        api.get(`/manufacturing/fault-cases/stats?kb=${mfgKb}`),
        api.get('/manufacturing/fault-cases/search', { params: { q: searchQ, top_k: 50, kb: mfgKb } }),
      ])
      if (gen !== genRef.current) return
      setFaultStats(statsRes)
      setFaultResults(searchRes?.results || [])
    } catch (e) {
      if (gen !== genRef.current) return
      console.error('[KG] 加载故障案例失败:', e)
    } finally {
      if (gen === genRef.current) setLoading(false)
    }
  }, [searchQ, mfgKb])

  const loadProcess = useCallback(async () => {
    const gen = ++genRef.current
    setLoading(true)
    try {
      const [catsRes, resultsRes] = await Promise.all([
        api.get(`/manufacturing/process-library/categories?kb=${mfgKb}`),
        api.get('/manufacturing/process-library/search', { params: { q: searchQ, limit: 50, kb: mfgKb } }),
      ])
      if (gen !== genRef.current) return
      setProcessCats(catsRes || {})
      setProcessResults(resultsRes?.results || [])
    } catch (e) {
      if (gen !== genRef.current) return
      console.error('[KG] 加载工艺库失败:', e)
    } finally {
      if (gen === genRef.current) setLoading(false)
    }
  }, [searchQ, mfgKb])

  // Clear stale data on KB switch
  useEffect(() => {
    setKgNodes([]); setKgEdges([]); setKgSummary(null)
    setFaultResults([]); setFaultStats(null)
    setProcessResults([]); setProcessCats({})
    // Load will be triggered by the next effect
  }, [mfgKb])

  useEffect(() => {
    if (activeTab === 'graph' || activeTab === 'nodes') loadGraph()
    else if (activeTab === 'faults') loadFaults()
    else if (activeTab === 'process') loadProcess()
  }, [activeTab, mfgKb])

  // Search
  const handleSearch = () => {
    if (activeTab === 'faults') loadFaults()
    else if (activeTab === 'process') loadProcess()
  }

  // ── Fault Case CRUD ───────────────────────────────

  const openFaultCreate = () => {
    setEditingFault(null)
    setFaultForm({ title: '', equipment_type: '', fault_category: '', phenomenon: '',
      root_cause: '', troubleshooting_steps: '', preventive_measures: '',
      severity: 'medium' })
    setFaultModalOpen(true)
  }

  const openFaultEdit = (c) => {
    setEditingFault(c)
    setFaultForm({
      title: c.title || '',
      equipment_type: c.equipment_type || '',
      fault_category: c.fault_category || '',
      phenomenon: c.phenomenon || '',
      root_cause: c.root_cause || '',
      troubleshooting_steps: (c.troubleshooting_steps || []).join('\n'),
      preventive_measures: (c.preventive_measures || []).join('\n'),
      severity: c.severity || 'medium',
    })
    setFaultModalOpen(true)
  }

  const handleSaveFault = async () => {
    setFaultSaving(true)
    try {
      const body = {
        ...faultForm,
        troubleshooting_steps: faultForm.troubleshooting_steps
          ? faultForm.troubleshooting_steps.split('\n').filter(Boolean) : [],
        preventive_measures: faultForm.preventive_measures
          ? faultForm.preventive_measures.split('\n').filter(Boolean) : [],
      }
      if (editingFault) {
        await api.put(`/manufacturing/fault-cases/${editingFault.id}`, body)
      } else {
        await api.post('/manufacturing/fault-cases', body)
      }
      setFaultModalOpen(false)
      loadFaults()
    } catch (e) {
      console.error('[KG] 保存故障案例失败:', e)
      alert('保存失败: ' + (e?.response?.data?.detail || e.message))
    } finally {
      setFaultSaving(false)
    }
  }

  const handleDeleteFault = async (caseId, title) => {
    if (!window.confirm(`确定要删除故障案例「${title}」吗？此操作不可撤销。`)) return
    try {
      await api.delete(`/manufacturing/fault-cases/${caseId}`)
      loadFaults()
    } catch (e) {
      console.error('[KG] 删除故障案例失败:', e)
      alert('删除失败: ' + (e?.response?.data?.detail || e.message))
    }
  }

  // ── Process Document CRUD ─────────────────────────

  const openProcessCreate = () => {
    setEditingProcess(null)
    setProcessForm({ title: '', category: '', text: '' })
    setProcessModalOpen(true)
  }

  const openProcessEdit = (p) => {
    setEditingProcess(p)
    setProcessForm({
      title: p.title || '',
      category: p.category || '',
      text: p.full_text || p.text_preview || '',
    })
    setProcessModalOpen(true)
  }

  const handleSaveProcess = async () => {
    setProcessSaving(true)
    try {
      const body = { title: processForm.title, text: processForm.text }
      if (processForm.category) body.category = processForm.category
      if (editingProcess) {
        await api.put(`/manufacturing/process-library/documents/${editingProcess.id}`, body)
      } else {
        await api.post('/manufacturing/process-library/documents', body)
      }
      setProcessModalOpen(false)
      loadProcess()
    } catch (e) {
      console.error('[KG] 保存工艺文档失败:', e)
      alert('保存失败: ' + (e?.response?.data?.detail || e.message))
    } finally {
      setProcessSaving(false)
    }
  }

  const handleDeleteProcess = async (docId, title) => {
    if (!window.confirm(`确定要删除工艺文档「${title}」吗？此操作不可撤销。`)) return
    try {
      await api.delete(`/manufacturing/process-library/documents/${docId}`)
      loadProcess()
    } catch (e) {
      console.error('[KG] 删除工艺文档失败:', e)
      alert('删除失败: ' + (e?.response?.data?.detail || e.message))
    }
  }

  // ── Detail View Handlers ──────────────────────────

  const openFaultDetail = (c) => {
    setViewingFault(c)
  }

  const openProcessDetail = async (p) => {
    setViewingProcess(p)
    // Fetch full document if available (search results only have text_preview)
    if (p.id) {
      setProcessDetailLoading(true)
      try {
        const res = await api.get(`/manufacturing/process-library/documents/${p.id}`)
        setProcessDetail(res?.document || res)
      } catch (e) {
        console.error('[KG] 加载工艺文档详情失败:', e)
        setProcessDetail(null)
      } finally {
        setProcessDetailLoading(false)
      }
    }
  }

  // Node detail + lineage
  const viewNodeDetail = async (nodeId) => {
    try {
      const [detailRes, lineageRes] = await Promise.all([
        api.get(`/manufacturing/knowledge-graph/nodes/${nodeId}?kb=${mfgKb}`),
        api.get(`/manufacturing/knowledge-graph/nodes/${nodeId}/lineage?kb=${mfgKb}`),
      ])
      setSelectedNode(detailRes?.node)
      setLineage(lineageRes)
    } catch (e) {
      console.error('[KG] 加载节点详情失败:', e)
    }
  }

  // Handle node click from D3 graph
  const handleGraphNodeClick = useCallback(async (node) => {
    setSelectedNode(node)
    if (node?.id) {
      try {
        const lineageRes = await api.get(`/manufacturing/knowledge-graph/nodes/${node.id}/lineage?kb=${mfgKb}`)
        setLineage(lineageRes)
      } catch (e) {
        console.error('[KG] 加载谱系失败:', e)
        setLineage(null)
      }
    }
  }, [mfgKb])

  // Node type color
  const nodeTypeColor = (type) => {
    const map = {
      knowledge_point: 'bg-sky-50 text-sky-600 border-sky-200',
      competition_topic: 'bg-sage-50 text-sage-600 border-sage-200',
      skill_point: 'bg-sky-50 text-sky-600 border-sky-200',
    }
    return map[type] || 'bg-cloud-100 text-ink-body border-cloud-300'
  }

  const nodeTypeLabel = (type) => {
    const map = { knowledge_point: '知识点', competition_topic: '赛题', skill_point: '技能' }
    return map[type] || type
  }

  return (
    <KnowledgeErrorBoundary>
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink-primary flex items-center gap-2">
            <Database size={22} className="text-sage-500" />
            知识库
          </h1>
          <p className="text-sm text-ink-muted mt-1">赛项知识图谱 · 故障案例 · 工艺文档</p>
          <div className="flex gap-1 mt-2">
            {[
              { to: '/manufacturing', label: '仪表板' },
              { to: '/manufacturing/knowledge', label: '知识库' },
              { to: '/manufacturing/agent', label: '智能体' },
            ].map(item => (
              <button key={item.to} onClick={() => navigate(item.to)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                  location.pathname === item.to
                    ? 'bg-sky-50 text-sky-600'
                    : 'text-ink-muted hover:text-ink-body hover:bg-cloud-100'
                }`}>
                {item.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <ManufacturingKBSelector
            mfgKb={mfgKb} kbList={kbList} loading={kbLoading} creating={creating}
            onChange={setMfgKb} onCreate={createMfgKb}
          />
          <button
            onClick={() => navigate(`/knowledge`)}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs border border-sky-200 dark:border-sky-800/30 text-sky-600 hover:bg-sky-50 transition-colors"
            title="跳转到通用知识库管理页面上传文档"
          >
            <BookOpen size={13} /> 上传文档
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-cloud-100 rounded-xl w-fit">
        {TABS.map(t => (
          <button key={t.key} onClick={() => { setActiveTab(t.key); setSelectedNode(null); setLineage(null); setViewingFault(null); setViewingProcess(null); setProcessDetail(null) }}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === t.key ? 'bg-white text-ink-primary shadow-sm' : 'text-ink-muted hover:text-ink-body'
            }`}>
            <t.icon size={15} /> {t.label}
          </button>
        ))}
      </div>

      {/* Search bar (faults & process) */}
      {(activeTab === 'faults' || activeTab === 'process') && (
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
            <input value={searchQ} onChange={e => setSearchQ(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder={activeTab === 'faults' ? '搜索故障现象、原因…' : '搜索工艺名称、参数…'}
              className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-cloud-300 text-sm bg-white
                focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-50 transition-all" />
          </div>
          <button onClick={handleSearch}
            className="btn-primary px-5 py-2.5 text-sm rounded-xl">搜索</button>
        </div>
      )}

      <AnimatePresence mode="wait">
        {/* ========== D3 GRAPH VISUALIZATION TAB ========== */}
        {activeTab === 'graph' && (
          <motion.div key="graph" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="space-y-4">
            {/* Stats cards */}
            {kgSummary && (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {[
                  { label: '节点总数', value: kgSummary.total_nodes, icon: Database, color: 'sky' },
                  { label: '关系总数', value: kgSummary.total_edges, icon: GitBranch, color: 'sage' },
                  { label: '节点类型', value: Object.keys(kgSummary.node_types || {}).length, icon: Layers, color: 'sky' },
                  { label: '关系类型', value: Object.keys(kgSummary.relation_types || {}).length, icon: Tag, color: 'amber' },
                ].map(s => {
                  const colorMap = {
                    sky: 'text-sky-400', sage: 'text-sage-400',
                    sky: 'text-sky-400', amber: 'text-amber-400',
                  }
                  return (
                  <div key={s.label} className="card p-4">
                    <s.icon size={16} className={`${colorMap[s.color] || 'text-ink-muted'} mb-2`} />
                    <p className="text-xl font-bold text-ink-primary">{s.value}</p>
                    <p className="text-xs text-ink-muted">{s.label}</p>
                  </div>
                  )
                })}
              </div>
            )}

            {/* Graph component — receives data via props */}
            <KnowledgeErrorBoundary>
            <KnowledgeGraphD3
              nodes={kgNodes}
              edges={kgEdges}
              loading={kgLoading}
              error={kgError}
              summary={kgSummary}
              onRetry={loadGraph}
              onNodeClick={handleGraphNodeClick}
            />
            </KnowledgeErrorBoundary>

            {/* Node detail panel (shown when node selected from graph or list) */}
            {selectedNode && (
              <motion.div
                initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                className="card p-4 space-y-3 ring-1 ring-sky-200 dark:ring-sky-800/30">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className={`px-2 py-0.5 rounded-md text-2xs border ${nodeTypeColor(selectedNode.node_type)}`}>
                      {nodeTypeLabel(selectedNode.node_type)}
                    </div>
                    <h4 className="text-sm font-semibold text-ink-body">{selectedNode.name}</h4>
                    {selectedNode.difficulty_level && (
                      <span className="text-2xs text-ink-muted">Lv.{selectedNode.difficulty_level}</span>
                    )}
                  </div>
                  <button onClick={() => setSelectedNode(null)} aria-label="关闭详情"
                    className="text-ink-muted hover:text-ink-body transition-colors">
                    <X size={16} aria-hidden="true" />
                  </button>
                </div>
                <p className="text-xs text-ink-body">{selectedNode.description || '暂无描述'}</p>
                {selectedNode.estimated_hours > 0 && (
                  <p className="text-2xs text-ink-muted">预计学时：{selectedNode.estimated_hours}h</p>
                )}

                {/* Lineage */}
                {lineage && (
                  <div className="grid grid-cols-3 gap-3 pt-3 border-t border-cloud-200">
                    <div className="p-2.5 rounded-lg bg-amber-50 text-xs">
                      <p className="font-medium text-amber-700 mb-1.5">前置知识 ({lineage.prerequisite_count || 0})</p>
                      {lineage.prerequisites?.length > 0 ? (
                        lineage.prerequisites.map(p => (
                          <div key={p.id} className="text-amber-800 py-0.5">• {p.name}</div>
                        ))
                      ) : (
                        <p className="text-amber-400 text-2xs">无前置依赖</p>
                      )}
                    </div>
                    <div className="p-2.5 rounded-lg bg-sky-50 text-xs flex items-center justify-center">
                      <div className="text-center">
                        <div className={`inline-block px-2 py-0.5 rounded-md text-2xs border mb-1 ${nodeTypeColor(selectedNode.node_type)}`}>
                          {nodeTypeLabel(selectedNode.node_type)}
                        </div>
                        <p className="text-sky-600 font-medium text-xs">当前节点</p>
                      </div>
                    </div>
                    <div className="p-2.5 rounded-lg bg-sage-50 text-xs">
                      <p className="font-medium text-sage-700 mb-1.5">进阶知识 ({lineage.advancement_count || 0})</p>
                      {lineage.advancements?.length > 0 ? (
                        lineage.advancements.map(a => (
                          <div key={a.id} className="text-sage-800 py-0.5">• {a.name}</div>
                        ))
                      ) : (
                        <p className="text-sage-400 text-2xs">无后续进阶</p>
                      )}
                    </div>
                  </div>
                )}
              </motion.div>
            )}
          </motion.div>
        )}

        {/* ========== NODE LIST TAB ========== */}
        {activeTab === 'nodes' && (
          <motion.div key="nodes" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="space-y-4">
            <div className="card p-0 overflow-hidden">
              <div className="p-4 border-b border-cloud-200 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-ink-body">知识节点</h3>
                <span className="text-xs text-ink-muted">{kgNodes.length} 个节点</span>
              </div>
              <div className="max-h-[420px] overflow-y-auto">
                {kgNodes.length > 0 ? kgNodes.slice(0, 100).map(node => (
                  <button key={node.id} onClick={() => viewNodeDetail(node.id)}
                    className={`w-full flex items-center gap-3 px-4 py-3 hover:bg-cloud-200 transition-colors border-b border-cloud-200 text-left ${
                      selectedNode?.id === node.id ? 'bg-sky-50' : ''
                    }`}>
                    <div className={`px-2 py-0.5 rounded-md text-2xs border ${nodeTypeColor(node.node_type)}`}>
                      {nodeTypeLabel(node.node_type)}
                    </div>
                    <span className="text-sm text-ink-body flex-1 truncate">{node.name}</span>
                    <span className="text-xs text-ink-muted">Lv.{node.difficulty_level || 1}</span>
                    <ChevronRight size={14} className="text-ink-muted" />
                  </button>
                )) : (
                  <p className="text-center text-sm text-ink-muted py-12">
                    {kgLoading ? '加载中…' : '暂无节点数据'}
                  </p>
                )}
              </div>
            </div>

            {/* Node detail (shared with graph tab) */}
            {selectedNode && (
              <motion.div
                initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                className="card p-4 space-y-3 ring-1 ring-sky-200 dark:ring-sky-800/30">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className={`px-2 py-0.5 rounded-md text-2xs border ${nodeTypeColor(selectedNode.node_type)}`}>
                      {nodeTypeLabel(selectedNode.node_type)}
                    </div>
                    <h4 className="text-sm font-semibold text-ink-body">{selectedNode.name}</h4>
                  </div>
                  <button onClick={() => setSelectedNode(null)} aria-label="关闭详情"
                    className="text-ink-muted hover:text-ink-body transition-colors">
                    <X size={16} aria-hidden="true" />
                  </button>
                </div>
                <p className="text-xs text-ink-body">{selectedNode.description || '暂无描述'}</p>
                {lineage && (
                  <div className="grid grid-cols-3 gap-3 pt-3 border-t border-cloud-200">
                    <div className="p-2.5 rounded-lg bg-amber-50 text-xs">
                      <p className="font-medium text-amber-700 mb-1.5">前置知识 ({lineage.prerequisite_count || 0})</p>
                      {lineage.prerequisites?.length > 0 ? (
                        lineage.prerequisites.map(p => <div key={p.id} className="text-amber-800 py-0.5">• {p.name}</div>)
                      ) : <p className="text-amber-400 text-2xs">无前置依赖</p>}
                    </div>
                    <div className="p-2.5 rounded-lg bg-sky-50 text-xs flex items-center justify-center">
                      <div className="text-center">
                        <div className={`inline-block px-2 py-0.5 rounded-md text-2xs border mb-1 ${nodeTypeColor(selectedNode.node_type)}`}>
                          {nodeTypeLabel(selectedNode.node_type)}
                        </div>
                        <p className="text-sky-600 font-medium text-xs">当前节点</p>
                      </div>
                    </div>
                    <div className="p-2.5 rounded-lg bg-sage-50 text-xs">
                      <p className="font-medium text-sage-700 mb-1.5">进阶知识 ({lineage.advancement_count || 0})</p>
                      {lineage.advancements?.length > 0 ? (
                        lineage.advancements.map(a => <div key={a.id} className="text-sage-800 py-0.5">• {a.name}</div>)
                      ) : <p className="text-sage-400 text-2xs">无后续进阶</p>}
                    </div>
                  </div>
                )}
              </motion.div>
            )}
          </motion.div>
        )}

        {/* ========== FAULT CASES TAB ========== */}
        {activeTab === 'faults' && (
          <motion.div key="faults" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-xs text-ink-muted">共 {faultStats?.total_cases || faultResults.length} 个案例</p>
              <button onClick={openFaultCreate}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-sky-500 text-white hover:bg-sky-600 transition-colors">
                <Plus size={13} /> 新建案例
              </button>
            </div>
            {faultStats && (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="card p-4">
                  <AlertTriangle size={16} className="text-amber-400 mb-2" />
                  <p className="text-xl font-bold text-ink-primary">{faultStats.total_cases}</p>
                  <p className="text-xs text-ink-muted">总案例数</p>
                </div>
                {faultStats.equipment_types && (
                  <div className="card p-4">
                    <Wrench size={16} className="text-sage-400 mb-2" />
                    <p className="text-xl font-bold text-ink-primary">{Object.keys(faultStats.equipment_types).length}</p>
                    <p className="text-xs text-ink-muted">设备类型</p>
                  </div>
                )}
                {faultStats.fault_categories && (
                  <div className="card p-4">
                    <Layers size={16} className="text-sky-400 mb-2" />
                    <p className="text-xl font-bold text-ink-primary">{Object.keys(faultStats.fault_categories).length}</p>
                    <p className="text-xs text-ink-muted">故障类别</p>
                  </div>
                )}
                {faultStats.severity_distribution && (
                  <div className="card p-4">
                    <AlertTriangle size={16} className="text-rose-400 mb-2" />
                    <p className="text-xl font-bold text-ink-primary">
                      {faultStats.severity_distribution.critical || faultStats.severity_distribution.high || 0}
                    </p>
                    <p className="text-xs text-ink-muted">高严重度</p>
                  </div>
                )}
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {faultResults.map((c, i) => (
                <motion.div key={c.id || i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  onClick={() => openFaultDetail(c)}
                  className="card p-4 hover:shadow-cloud-md transition-shadow cursor-pointer">
                  <div className="flex items-start justify-between mb-2">
                    <h4 className="text-sm font-semibold text-ink-primary hover:text-sky-600 transition-colors">{c.title}</h4>
                    <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                      <button onClick={() => openFaultEdit(c)}
                        className="p-1 rounded text-ink-muted hover:text-sage-600 hover:bg-sage-50 transition-colors"
                        title="编辑案例">
                        <Edit3 size={12} />
                      </button>
                      <button onClick={() => handleDeleteFault(c.id, c.title)}
                        className="p-1 rounded text-ink-muted hover:text-rose-600 hover:bg-rose-50 transition-colors"
                        title="删除案例">
                        <Trash2 size={12} />
                      </button>
                      <span className={`badge text-2xs ${BADGE_COLORS[c.severity] || 'badge-info'}`}>
                        {SEVERITY_LABELS[c.severity] || c.severity || '中'}
                      </span>
                    </div>
                  </div>
                  <p className="text-xs text-ink-body mb-3 line-clamp-2">{c.phenomenon}</p>
                  <div className="flex flex-wrap gap-1.5 mb-3">
                    <span className="px-2 py-0.5 rounded-md text-2xs bg-cloud-100 text-ink-body">
                      {c.equipment_type}
                    </span>
                    <span className="px-2 py-0.5 rounded-md text-2xs bg-cloud-100 text-ink-body">
                      {c.fault_category}
                    </span>
                    {c.score && (
                      <span className="px-2 py-0.5 rounded-md text-2xs bg-sky-50 text-sky-600">
                        匹配 {(c.score * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  {c.root_cause && (
                    <div className="p-2 rounded-lg bg-cloud-200 text-xs text-ink-body">
                      <span className="font-medium text-amber-600">根因：</span>{c.root_cause}
                    </div>
                  )}
                  {c.troubleshooting_steps?.length > 0 && (
                    <details className="mt-2" onClick={e => e.stopPropagation()}>
                      <summary className="text-xs text-sage-600 cursor-pointer font-medium">排除步骤 ({c.troubleshooting_steps.length} 步)</summary>
                      <ol className="mt-1 pl-4 text-xs text-ink-body space-y-0.5 list-decimal">
                        {c.troubleshooting_steps.map((s, j) => <li key={j}>{s}</li>)}
                      </ol>
                    </details>
                  )}
                </motion.div>
              ))}
            </div>
            {faultResults.length === 0 && !loading && (
              <p className="text-center text-sm text-ink-muted py-12">暂无故障案例数据</p>
            )}
          </motion.div>
        )}

        {/* ========== PROCESS LIBRARY TAB ========== */}
        {activeTab === 'process' && (
          <motion.div key="process" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-xs text-ink-muted">共 {processResults.length} 份文档</p>
              <button onClick={openProcessCreate}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-sky-500 text-white hover:bg-sky-600 transition-colors">
                <Plus size={13} /> 新建工艺文档
              </button>
            </div>
            {Object.keys(processCats).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(processCats).map(([cat, count]) => (
                  <div key={cat} className="px-3 py-1.5 rounded-lg bg-cloud-100 text-xs font-medium text-ink-body">
                    {cat}: <span className="text-ink-primary">{count}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {processResults.map((p, i) => (
                <motion.div key={p.id || i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  onClick={() => openProcessDetail(p)}
                  className="card p-4 hover:shadow-cloud-md transition-shadow cursor-pointer">
                  <div className="flex items-start justify-between mb-2">
                    <h4 className="text-sm font-semibold text-ink-primary hover:text-sky-600 transition-colors">{p.title}</h4>
                    <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                      <button onClick={() => openProcessEdit(p)}
                        className="p-1 rounded text-ink-muted hover:text-sage-600 hover:bg-sage-50 transition-colors"
                        title="编辑文档">
                        <Edit3 size={12} />
                      </button>
                      <button onClick={() => handleDeleteProcess(p.id, p.title)}
                        className="p-1 rounded text-ink-muted hover:text-rose-600 hover:bg-rose-50 transition-colors"
                        title="删除文档">
                        <Trash2 size={12} />
                      </button>
                      <span className="badge badge-info text-2xs">{p.category}</span>
                    </div>
                  </div>
                  <p className="text-xs text-ink-muted mb-3 line-clamp-2">{p.text_preview}</p>
                  {p.parameters?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {p.parameters.map((pm, j) => (
                        <span key={j} className="px-2 py-0.5 rounded-md text-2xs bg-sage-50 text-sage-700 border border-sage-100">
                          {pm.name}: {pm.value}{pm.unit}
                        </span>
                      ))}
                    </div>
                  )}
                </motion.div>
              ))}
            </div>
            {processResults.length === 0 && !loading && (
              <p className="text-center text-sm text-ink-muted py-12">暂无工艺文档数据</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ===== Fault Case Modal ===== */}
      {faultModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setFaultModalOpen(false)} role="dialog" aria-modal="true" aria-label={editingFault ? '编辑故障案例' : '新建故障案例'}>
          <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto"
            onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-ink-primary mb-4">
              {editingFault ? '编辑故障案例' : '新建故障案例'}
            </h3>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-ink-body">标题 *</label>
                <input value={faultForm.title || ''} onChange={e => setFaultForm({...faultForm, title: e.target.value})}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                  placeholder="如：数控机床主轴异响" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-ink-body">设备类型</label>
                  <input value={faultForm.equipment_type || ''} onChange={e => setFaultForm({...faultForm, equipment_type: e.target.value})}
                    className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                    placeholder="如：数控车床" />
                </div>
                <div>
                  <label className="text-xs font-medium text-ink-body">故障类别</label>
                  <input value={faultForm.fault_category || ''} onChange={e => setFaultForm({...faultForm, fault_category: e.target.value})}
                    className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                    placeholder="如：机械故障" />
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-ink-body">故障现象 *</label>
                <textarea value={faultForm.phenomenon || ''} onChange={e => setFaultForm({...faultForm, phenomenon: e.target.value})} rows={2}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                  placeholder="描述故障的表现…" />
              </div>
              <div>
                <label className="text-xs font-medium text-ink-body">根本原因 *</label>
                <input value={faultForm.root_cause || ''} onChange={e => setFaultForm({...faultForm, root_cause: e.target.value})}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                  placeholder="如：轴承磨损导致间隙过大" />
              </div>
              <div>
                <label className="text-xs font-medium text-ink-body">排除步骤（每行一步）</label>
                <textarea value={faultForm.troubleshooting_steps || ''} onChange={e => setFaultForm({...faultForm, troubleshooting_steps: e.target.value})} rows={3}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400 font-mono text-xs"
                  placeholder="1. 检查轴承温度&#10;2. 测量主轴径向跳动&#10;3. …" />
              </div>
              <div>
                <label className="text-xs font-medium text-ink-body">预防措施（每行一条）</label>
                <textarea value={faultForm.preventive_measures || ''} onChange={e => setFaultForm({...faultForm, preventive_measures: e.target.value})} rows={2}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400 font-mono text-xs"
                  placeholder="1. 定期更换轴承&#10;2. …" />
              </div>
              <div>
                <label className="text-xs font-medium text-ink-body">严重程度</label>
                <select value={faultForm.severity || 'medium'} onChange={e => setFaultForm({...faultForm, severity: e.target.value})}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400">
                  {SEVERITY_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex gap-2 mt-5 pt-4 border-t border-cloud-200">
              <button onClick={handleSaveFault} disabled={faultSaving || !faultForm.title?.trim() || !faultForm.phenomenon?.trim() || !faultForm.root_cause?.trim()}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-sky-500 text-white hover:bg-sky-600 disabled:opacity-40 transition-colors">
                {faultSaving && <Loader2 size={14} className="animate-spin" />}
                {faultSaving ? '保存中…' : (editingFault ? '更新案例' : '创建案例')}
              </button>
              <button onClick={() => setFaultModalOpen(false)}
                className="px-4 py-2 rounded-lg text-sm border border-cloud-300 text-ink-muted hover:bg-cloud-200 transition-colors">取消</button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Fault Case Detail Modal ===== */}
      {viewingFault && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setViewingFault(null)} role="dialog" aria-modal="true" aria-label={`故障案例详情: ${viewingFault.title}`}>
          <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-ink-primary">{viewingFault.title}</h3>
                <div className="flex items-center gap-2 mt-1">
                  <span className={`badge text-2xs ${BADGE_COLORS[viewingFault.severity] || 'badge-info'}`}>
                    {SEVERITY_LABELS[viewingFault.severity] || viewingFault.severity || '中'}
                  </span>
                  {viewingFault.equipment_type && (
                    <span className="px-2 py-0.5 rounded-md text-2xs bg-cloud-100 text-ink-body">{viewingFault.equipment_type}</span>
                  )}
                  {viewingFault.fault_category && (
                    <span className="px-2 py-0.5 rounded-md text-2xs bg-cloud-100 text-ink-body">{viewingFault.fault_category}</span>
                  )}
                </div>
              </div>
              <button onClick={() => setViewingFault(null)}
                className="p-1 rounded text-ink-muted hover:text-ink-body hover:bg-cloud-100 transition-colors">
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            {/* Phenomenon */}
            <div className="mb-4">
              <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">故障现象</h4>
              <p className="text-sm text-ink-body bg-cloud-200 rounded-lg p-3">{viewingFault.phenomenon || '暂无描述'}</p>
            </div>

            {/* Root cause */}
            <div className="mb-4">
              <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">根本原因</h4>
              <div className="p-3 rounded-lg bg-amber-50 text-sm text-amber-800 border border-amber-100">
                {viewingFault.root_cause || '未指定'}
              </div>
            </div>

            {/* Troubleshooting steps */}
            {viewingFault.troubleshooting_steps?.length > 0 && (
              <div className="mb-4">
                <h4 className="text-xs font-semibold text-sage-500 uppercase tracking-wide mb-1">
                  排除步骤 ({viewingFault.troubleshooting_steps.length} 步)
                </h4>
                <ol className="space-y-1.5">
                  {viewingFault.troubleshooting_steps.map((s, j) => (
                    <li key={j} className="flex gap-2 text-sm text-ink-body">
                      <span className="flex-shrink-0 w-5 h-5 rounded-full bg-sage-100 text-sage-600 text-2xs flex items-center justify-center font-medium mt-0.5">
                        {j + 1}
                      </span>
                      {s}
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {/* Preventive measures */}
            {viewingFault.preventive_measures?.length > 0 && (
              <div className="mb-4">
                <h4 className="text-xs font-semibold text-sky-500 uppercase tracking-wide mb-1">
                  预防措施 ({viewingFault.preventive_measures.length} 条)
                </h4>
                <ul className="space-y-1.5">
                  {viewingFault.preventive_measures.map((m, j) => (
                    <li key={j} className="flex gap-2 text-sm text-ink-body">
                      <span className="flex-shrink-0 text-sky-400 mt-0.5">💡</span>
                      {m}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Occurrence count */}
            {viewingFault.occurrence_count > 0 && (
              <div className="mb-4">
                <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">发生次数</h4>
                <p className="text-sm text-ink-body">{viewingFault.occurrence_count} 次</p>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-2 pt-4 border-t border-cloud-200">
              <button onClick={() => { setViewingFault(null); openFaultEdit(viewingFault); }}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-sage-200 text-sage-600 hover:bg-sage-50 transition-colors">
                <Edit3 size={14} /> 编辑
              </button>
              <button onClick={() => { const c = viewingFault; setViewingFault(null); handleDeleteFault(c.id, c.title); }}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-rose-200 text-rose-600 hover:bg-rose-50 transition-colors">
                <Trash2 size={14} /> 删除
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Process Document Modal ===== */}
      {processModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setProcessModalOpen(false)} role="dialog" aria-modal="true" aria-label={editingProcess ? "编辑工艺文档" : "新建工艺文档"}>
          <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto"
            onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-ink-primary mb-4">
              {editingProcess ? '编辑工艺文档' : '新建工艺文档'}
            </h3>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-ink-body">文档标题 *</label>
                <input value={processForm.title || ''} onChange={e => setProcessForm({...processForm, title: e.target.value})}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                  placeholder="如：焊接工艺规范 Q235" />
              </div>
              <div>
                <label className="text-xs font-medium text-ink-body">工艺类别</label>
                <select value={processForm.category || ''} onChange={e => setProcessForm({...processForm, category: e.target.value})}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400">
                  <option value="">（自动识别）</option>
                  <option value="machining">机加工</option>
                  <option value="welding">焊接</option>
                  <option value="assembly">装配</option>
                  <option value="inspection">检测</option>
                  <option value="heat_treatment">热处理</option>
                  <option value="casting">铸造</option>
                  <option value="forming">成型</option>
                  <option value="general">通用</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-medium text-ink-body">工艺内容 *</label>
                <textarea value={processForm.text || ''} onChange={e => setProcessForm({...processForm, text: e.target.value})} rows={8}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                  placeholder="输入工艺文档内容，系统会自动识别类别和参数…" />
              </div>
            </div>
            <div className="flex gap-2 mt-5 pt-4 border-t border-cloud-200">
              <button onClick={handleSaveProcess} disabled={processSaving || !processForm.title?.trim() || !processForm.text?.trim()}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-sky-500 text-white hover:bg-sky-600 disabled:opacity-40 transition-colors">
                {processSaving && <Loader2 size={14} className="animate-spin" />}
                {processSaving ? '保存中…' : (editingProcess ? '更新文档' : '创建文档')}
              </button>
              <button onClick={() => setProcessModalOpen(false)}
                className="px-4 py-2 rounded-lg text-sm border border-cloud-300 text-ink-muted hover:bg-cloud-200 transition-colors">取消</button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Process Document Detail Modal ===== */}
      {viewingProcess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => { setViewingProcess(null); setProcessDetail(null) }} role="dialog" aria-modal="true" aria-label="工艺文档详情">
          <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-ink-primary">{viewingProcess.title}</h3>
                <div className="flex items-center gap-2 mt-1">
                  <span className="badge badge-info text-2xs">{viewingProcess.category}</span>
                  {viewingProcess.ingested_at && (
                    <span className="text-2xs text-ink-muted">
                      {new Date(viewingProcess.ingested_at).toLocaleDateString('zh-CN')}
                    </span>
                  )}
                </div>
              </div>
              <button onClick={() => { setViewingProcess(null); setProcessDetail(null) }}
                className="p-1 rounded text-ink-muted hover:text-ink-body hover:bg-cloud-100 transition-colors">
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            {/* Parameters */}
            {viewingProcess.parameters?.length > 0 && (
              <div className="mb-4">
                <h4 className="text-xs font-semibold text-sage-500 uppercase tracking-wide mb-1">
                  工艺参数 ({viewingProcess.parameters.length})
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {viewingProcess.parameters.map((pm, j) => (
                    <span key={j} className="px-2 py-0.5 rounded-md text-xs bg-sage-50 text-sage-700 border border-sage-100">
                      {pm.name}: {pm.value}{pm.unit}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Full content */}
            <div className="mb-4">
              <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">文档内容</h4>
              {processDetailLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 size={20} className="animate-spin text-ink-muted" />
                </div>
              ) : (
                <div className="p-3 rounded-lg bg-cloud-200 text-sm text-ink-body whitespace-pre-wrap max-h-64 overflow-y-auto">
                  {processDetail?.full_text || processDetail?.text_preview || viewingProcess.text_preview || '暂无内容'}
                </div>
              )}
            </div>

            {/* File info */}
            {viewingProcess.file_path && (
              <div className="mb-4">
                <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">源文件</h4>
                <p className="text-xs text-ink-muted font-mono truncate">{viewingProcess.file_path}</p>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-2 pt-4 border-t border-cloud-200">
              <button onClick={() => { setViewingProcess(null); setProcessDetail(null); openProcessEdit(viewingProcess); }}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-sage-200 text-sage-600 hover:bg-sage-50 transition-colors">
                <Edit3 size={14} /> 编辑
              </button>
              <button onClick={() => { const p = viewingProcess; setViewingProcess(null); setProcessDetail(null); handleDeleteProcess(p.id, p.title); }}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-rose-200 text-rose-600 hover:bg-rose-50 transition-colors">
                <Trash2 size={14} /> 删除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </KnowledgeErrorBoundary>
  )
}
