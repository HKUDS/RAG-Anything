import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Search, Database, AlertTriangle, Wrench, BookOpen,
  GitBranch, ChevronRight, ArrowLeft, Tag, Layers, Filter, X, GitGraph, AlertCircle,
  Plus, Edit3, Trash2, Loader2
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '../utils/api'
import { useAutoRepairKB } from '../hooks/useAutoRepairKB'
import { useAuth } from '../context/AuthContext'
import AutoRepairKBSelector from '../components/AutoRepairKBSelector'
import KnowledgeGraphD3 from '../components/KnowledgeGraphD3'
import AutoRepairKBState from '../components/AutoRepairKBState'

// 轻量错误边界，避免单点崩溃导致整页空白
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
  { key: 'cases', icon: BookOpen, label: '案例库' },
]

const CASE_TYPE_FILTERS = [
  { key: '', icon: Layers, label: '全部' },
  { key: 'fault', icon: AlertTriangle, label: '故障案例' },
  { key: 'process', icon: Wrench, label: '维修工艺' },
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

export default function AutoRepairKnowledgePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { hasPermission } = useAuth()
  const canManageCases = hasPermission('autorepair:write')
  const canWriteKnowledge = hasPermission('kb:write')
  const [activeTab, setActiveTab] = useState('graph')
  const [kgNodes, setKgNodes] = useState([])
  const [kgEdges, setKgEdges] = useState([])
  const [kgSummary, setKgSummary] = useState(null)
  const [kgLoading, setKgLoading] = useState(false)
  const [kgError, setKgError] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [lineage, setLineage] = useState(null)
  // 统一案例库状态
  const [caseResults, setCaseResults] = useState([])
  const [caseStats, setCaseStats] = useState(null)
  const [caseTypeFilter, setCaseTypeFilter] = useState('')  // '' | 'fault' | 'process'
  const [searchQ, setSearchQ] = useState('')
  const [loading, setLoading] = useState(false)
  // 统一增删改查状态
  const [caseModalOpen, setCaseModalOpen] = useState(false)
  const [editingCase, setEditingCase] = useState(null)
  const [caseForm, setCaseForm] = useState({})
  const [caseSaving, setCaseSaving] = useState(false)
  // 详情视图状态
  const [viewingCase, setViewingCase] = useState(null)
  const { arKb, setArKb, kbList, kbLoading, kbError, creating, canCreateArKb, createArKb, refreshKbList } = useAutoRepairKB()

  // 生成计数器，用于取消过期的进行中请求
  const genRef = useRef(0)

  // ---- 知识图谱数据加载（统一）----
  const loadGraph = useCallback(async () => {
    if (!arKb) {
      setKgNodes([]); setKgEdges([]); setKgSummary(null); setKgLoading(false)
      return
    }
    const gen = ++genRef.current
    setKgLoading(true)
    setKgError(null)
    try {
      const [sumRes, nodesRes, edgesRes] = await Promise.all([
        api.get(`/autorepair/knowledge-graph/summary?kb=${arKb}`),
        api.get('/autorepair/knowledge-graph/nodes', { params: { limit: 2000, kb: arKb } }),
        api.get('/autorepair/knowledge-graph/edges', { params: { limit: 5000, kb: arKb } }),
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
  }, [arKb])

  // 统一案例加载器
  const loadCases = useCallback(async () => {
    if (!arKb) {
      setCaseResults([]); setCaseStats(null); setLoading(false)
      return
    }
    const gen = ++genRef.current
    setLoading(true)
    try {
      const [statsRes, searchRes] = await Promise.all([
        api.get(`/autorepair/cases/stats?kb=${arKb}`),
        api.get('/autorepair/cases/search', { params: { q: searchQ, case_type: caseTypeFilter, top_k: 50, kb: arKb } }),
      ])
      if (gen !== genRef.current) return
      setCaseStats(statsRes)
      setCaseResults(searchRes?.results || [])
    } catch (e) {
      if (gen !== genRef.current) return
      console.error('[KG] 加载案例库失败:', e)
    } finally {
      if (gen === genRef.current) setLoading(false)
    }
  }, [searchQ, caseTypeFilter, arKb])

  // 切换知识库时清理旧数据
  useEffect(() => {
    genRef.current += 1
    setKgNodes([]); setKgEdges([]); setKgSummary(null)
    setCaseResults([]); setCaseStats(null)
    // 下一轮 effect 会触发加载
  }, [arKb])

  useEffect(() => {
    if (kbLoading || !arKb) return
    if (activeTab === 'graph' || activeTab === 'nodes') loadGraph()
    else if (activeTab === 'cases') loadCases()
  }, [activeTab, arKb, kbLoading, loadCases, loadGraph])

  // 搜索
  const handleSearch = () => {
    if (arKb && activeTab === 'cases') loadCases()
  }

  // ── 统一案例增删改查 ─────────────────────────────

  const openCaseCreate = (caseType = 'fault') => {
    if (!canManageCases || !arKb) return
    setEditingCase(null)
    if (caseType === 'fault') {
      setCaseForm({ case_type: 'fault', title: '', equipment_type: '', fault_category: '',
        phenomenon: '', root_cause: '', troubleshooting_steps: '', preventive_measures: '',
        severity: 'medium' })
    } else {
      setCaseForm({ case_type: 'process', title: '', category: '', text: '' })
    }
    setCaseModalOpen(true)
  }

  const openCaseEdit = (c) => {
    if (!canManageCases || !arKb) return
    setEditingCase(c)
    if (c.case_type === 'fault') {
      setCaseForm({
        case_type: 'fault', title: c.title || '',
        equipment_type: c.equipment_type || '', fault_category: c.fault_category || '',
        phenomenon: c.phenomenon || '', root_cause: c.root_cause || '',
        troubleshooting_steps: (c.troubleshooting_steps || []).join('\n'),
        preventive_measures: (c.preventive_measures || []).join('\n'),
        severity: c.severity || 'medium',
      })
    } else {
      setCaseForm({
        case_type: 'process', title: c.title || '',
        category: c.category || '',
        text: c.full_text || c.text_preview || '',
      })
    }
    setCaseModalOpen(true)
  }

  const handleSaveCase = async () => {
    if (!canManageCases || !arKb) return
    setCaseSaving(true)
    try {
      const body = { case_type: caseForm.case_type, title: caseForm.title }
      if (caseForm.case_type === 'fault') {
        Object.assign(body, {
          equipment_type: caseForm.equipment_type || '',
          fault_category: caseForm.fault_category || '',
          phenomenon: caseForm.phenomenon || '',
          root_cause: caseForm.root_cause || '',
          troubleshooting_steps: caseForm.troubleshooting_steps
            ? caseForm.troubleshooting_steps.split('\n').filter(Boolean) : [],
          preventive_measures: caseForm.preventive_measures
            ? caseForm.preventive_measures.split('\n').filter(Boolean) : [],
          severity: caseForm.severity || 'medium',
        })
      } else {
        Object.assign(body, {
          category: caseForm.category || '',
          text: caseForm.text || '',
        })
      }
      if (editingCase) {
        await api.put(`/autorepair/cases/${editingCase.id}`, body)
      } else {
        await api.post('/autorepair/cases', body)
      }
      setCaseModalOpen(false)
      loadCases()
    } catch (e) {
      console.error('[KG] 保存案例失败:', e)
      alert('保存失败: ' + (e?.response?.data?.detail || e.message))
    } finally {
      setCaseSaving(false)
    }
  }

  const handleDeleteCase = async (caseId, title) => {
    if (!canManageCases || !arKb) return
    if (!window.confirm(`确定要删除案例「${title}」吗？此操作不可撤销。`)) return
    try {
      await api.delete(`/autorepair/cases/${caseId}`)
      loadCases()
    } catch (e) {
      console.error('[KG] 删除案例失败:', e)
      alert('删除失败: ' + (e?.response?.data?.detail || e.message))
    }
  }

  // ── 详情视图处理 ──────────────────────────

  const openCaseDetail = (c) => {
    setViewingCase(c)
  }

  // 节点详情与谱系
  const viewNodeDetail = async (nodeId) => {
    if (!arKb) return
    try {
      const [detailRes, lineageRes] = await Promise.all([
        api.get(`/autorepair/knowledge-graph/nodes/${nodeId}?kb=${arKb}`),
        api.get(`/autorepair/knowledge-graph/nodes/${nodeId}/lineage?kb=${arKb}`),
      ])
      setSelectedNode(detailRes?.node)
      setLineage(lineageRes)
    } catch (e) {
      console.error('[KG] 加载节点详情失败:', e)
    }
  }

  // 处理 D3 图谱中的节点点击
  const handleGraphNodeClick = useCallback(async (node) => {
    if (!arKb) return
    setSelectedNode(node)
    if (node?.id) {
      try {
        const lineageRes = await api.get(`/autorepair/knowledge-graph/nodes/${node.id}/lineage?kb=${arKb}`)
        setLineage(lineageRes)
      } catch (e) {
        console.error('[KG] 加载谱系失败:', e)
        setLineage(null)
      }
    }
  }, [arKb])

  // 节点类型颜色
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
      {/* 头部 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink-primary flex items-center gap-2">
            <Database size={22} className="text-sage-500" />
            知识库
          </h1>
          <p className="text-sm text-ink-muted mt-1">赛项知识图谱 · 统一案例库</p>
          <div className="flex gap-1 mt-2">
            {[
              { to: '/autorepair', label: '仪表板' },
              { to: '/autorepair/knowledge', label: '知识库' },
              canManageCases ? { to: '/autorepair/agent', label: '智能体' } : null,
            ].filter(Boolean).map(item => (
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
          <AutoRepairKBSelector
            arKb={arKb} kbList={kbList} loading={kbLoading} creating={creating}
            onChange={setArKb} onCreate={createArKb} canCreate={canCreateArKb}
          />
          {canWriteKnowledge && <button
            onClick={() => navigate(`/knowledge`)}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs border border-sky-200 dark:border-sky-800/30 text-sky-600 hover:bg-sky-50 transition-colors"
            title="跳转到通用知识库管理页面上传文档"
          >
            <BookOpen size={13} /> 上传文档
          </button>}
        </div>
      </div>

      {!kbLoading && !arKb && <AutoRepairKBState error={kbError} onRetry={refreshKbList} />}

      {/* 标签页 */}
      <div className="flex gap-1 p-1 bg-cloud-100 rounded-xl w-fit">
        {TABS.map(t => (
          <button key={t.key} onClick={() => { setActiveTab(t.key); setSelectedNode(null); setLineage(null); setViewingCase(null) }}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === t.key ? 'bg-white text-ink-primary shadow-sm' : 'text-ink-muted hover:text-ink-body'
            }`}>
            <t.icon size={15} /> {t.label}
          </button>
        ))}
      </div>

      {/* 搜索栏（案例标签页） */}
      {activeTab === 'cases' && (
        <div className="space-y-3">
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
              <input value={searchQ} onChange={e => setSearchQ(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                placeholder="搜索案例名称、故障现象、根因、工艺内容…"
                className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-cloud-300 text-sm bg-white
                  focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-50 transition-all" />
            </div>
            <button onClick={handleSearch}
              className="btn-primary px-5 py-2.5 text-sm rounded-xl">搜索</button>
          </div>
          {/* 案例类型筛选标签 */}
          <div className="flex items-center gap-1.5">
            {CASE_TYPE_FILTERS.map(f => (
              <button key={f.key} onClick={() => setCaseTypeFilter(f.key)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  caseTypeFilter === f.key
                    ? 'bg-sky-500 text-white shadow-sm'
                    : 'bg-cloud-100 text-ink-body hover:bg-cloud-200'
                }`}>
                <f.icon size={12} /> {f.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <AnimatePresence mode="wait">
        {/* ========== D3 图谱可视化标签页 ========== */}
        {activeTab === 'graph' && (
          <motion.div key="graph" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="space-y-4">
            {/* 统计卡片 */}
            {kgSummary && (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {[
                  { label: '节点总数', value: kgSummary.total_nodes, icon: Database, color: 'sky' },
                  { label: '关系总数', value: kgSummary.total_edges, icon: GitBranch, color: 'sage' },
                  { label: '节点类型', value: Object.keys(kgSummary.node_types || {}).length, icon: Layers, color: 'sky' },
                  { label: '关系类型', value: Object.keys(kgSummary.relation_types || {}).length, icon: Tag, color: 'amber' },
                ].map(s => {
                  const colorMap = {
                    sky: 'text-sky-400',
                    sage: 'text-sage-400',
                    amber: 'text-amber-400',
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

            {/* 图谱组件：通过 props 接收数据 */}
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

            {/* 节点详情面板：从图谱或列表选中节点时显示 */}
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

                {/* 谱系 */}
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

        {/* ========== 节点列表标签页 ========== */}
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

            {/* 节点详情（与图谱标签页共用） */}
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

        {/* ========== 统一案例标签页 ========== */}
        {activeTab === 'cases' && (
          <motion.div key="cases" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-xs text-ink-muted">
                共 {caseResults.length} 个案例
                {caseStats && ` (故障 ${caseStats.fault_total || 0} · 工艺 ${caseStats.process_total || 0})`}
              </p>
              <div className="flex items-center gap-2">
                {canManageCases && (
                  <>
                    <button onClick={() => openCaseCreate('fault')}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-500 text-white hover:bg-amber-600 transition-colors">
                      <AlertTriangle size={13} /> 新建故障案例
                    </button>
                    <button onClick={() => openCaseCreate('process')}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-sky-500 text-white hover:bg-sky-600 transition-colors">
                      <Wrench size={13} /> 新建工艺案例
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* 统计卡片 */}
            {caseStats && (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="card p-4">
                  <BookOpen size={16} className="text-sky-400 mb-2" />
                  <p className="text-xl font-bold text-ink-primary">{caseStats.total_cases || 0}</p>
                  <p className="text-xs text-ink-muted">总案例数</p>
                </div>
                <div className="card p-4">
                  <AlertTriangle size={16} className="text-amber-400 mb-2" />
                  <p className="text-xl font-bold text-ink-primary">{caseStats.fault_total || 0}</p>
                  <p className="text-xs text-ink-muted">故障案例</p>
                </div>
                <div className="card p-4">
                  <Wrench size={16} className="text-sage-400 mb-2" />
                  <p className="text-xl font-bold text-ink-primary">{caseStats.process_total || 0}</p>
                  <p className="text-xs text-ink-muted">维修工艺</p>
                </div>
                <div className="card p-4">
                  <Layers size={16} className="text-rose-400 mb-2" />
                  <p className="text-xl font-bold text-ink-primary">
                    {Object.keys(caseStats.equipment_types || {}).length + Object.keys(caseStats.fault_categories || {}).length}
                  </p>
                  <p className="text-xs text-ink-muted">分类维度</p>
                </div>
              </div>
            )}

            {/* 分类标签（仅工艺案例） */}
            {caseStats?.process_categories && Object.keys(caseStats.process_categories).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(caseStats.process_categories).map(([cat, count]) => (
                  <div key={cat} className="px-3 py-1.5 rounded-lg bg-cloud-100 text-xs font-medium text-ink-body">
                    {cat}: <span className="text-ink-primary">{count}</span>
                  </div>
                ))}
              </div>
            )}

            {/* 案例卡片网格 */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {caseResults.map((c, i) => (
                <motion.div key={c.id || i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  onClick={() => openCaseDetail(c)}
                  className="card p-4 hover:shadow-cloud-md transition-shadow cursor-pointer">
                  <div className="flex items-start justify-between mb-2">
                    <h4 className="text-sm font-semibold text-ink-primary hover:text-sky-600 transition-colors">{c.title}</h4>
                    <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                      {canManageCases && (
                        <>
                          <button onClick={() => openCaseEdit(c)}
                            className="p-1 rounded text-ink-muted hover:text-sage-600 hover:bg-sage-50 transition-colors"
                            title="编辑案例">
                            <Edit3 size={12} />
                          </button>
                          <button onClick={() => handleDeleteCase(c.id, c.title)}
                            className="p-1 rounded text-ink-muted hover:text-rose-600 hover:bg-rose-50 transition-colors"
                            title="删除案例">
                            <Trash2 size={12} />
                          </button>
                        </>
                      )}
                      <span className={`badge text-2xs ${c.case_type === 'fault' ? 'badge-warning' : 'badge-info'}`}>
                        {c.case_type === 'fault' ? '故障' : '工艺'}
                      </span>
                    </div>
                  </div>

                  {/* 故障案例专属卡片内容 */}
                  {c.case_type === 'fault' && (
                    <>
                      <p className="text-xs text-ink-body mb-3 line-clamp-2">{c.phenomenon}</p>
                      <div className="flex flex-wrap gap-1.5 mb-3">
                        {c.equipment_type && (
                          <span className="px-2 py-0.5 rounded-md text-2xs bg-cloud-100 text-ink-body">{c.equipment_type}</span>
                        )}
                        {c.fault_category && (
                          <span className="px-2 py-0.5 rounded-md text-2xs bg-cloud-100 text-ink-body">{c.fault_category}</span>
                        )}
                        <span className={`badge text-2xs ${BADGE_COLORS[c.severity] || 'badge-info'}`}>
                          {SEVERITY_LABELS[c.severity] || c.severity || '中'}
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
                    </>
                  )}

                  {/* 工艺案例专属卡片内容 */}
                  {c.case_type === 'process' && (
                    <>
                      <p className="text-xs text-ink-muted mb-3 line-clamp-2">{c.text_preview}</p>
                      <div className="flex flex-wrap gap-1.5 mb-3">
                        <span className="badge badge-info text-2xs">{c.category}</span>
                      </div>
                      {c.parameters?.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {c.parameters.map((pm, j) => (
                            <span key={j} className="px-2 py-0.5 rounded-md text-2xs bg-sage-50 text-sage-700 border border-sage-100">
                              {pm.name}: {pm.value}{pm.unit}
                            </span>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </motion.div>
              ))}
            </div>
            {caseResults.length === 0 && !loading && (
              <p className="text-center text-sm text-ink-muted py-12">暂无案例数据</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ===== 统一案例创建/编辑弹窗 ===== */}
      {caseModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setCaseModalOpen(false)} role="dialog" aria-modal="true" aria-label={editingCase ? '编辑案例' : '新建案例'}>
          <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto"
            onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-ink-primary mb-4">
              {editingCase ? '编辑案例' : '新建案例'}
              <span className="ml-2 text-xs font-normal text-ink-muted">
                ({caseForm.case_type === 'fault' ? '故障案例' : '维修工艺'})
              </span>
            </h3>

            {/* 案例类型切换（仅创建时显示） */}
            {!editingCase && (
              <div className="flex gap-2 mb-4">
                {[
                  { key: 'fault', icon: AlertTriangle, label: '故障案例' },
                  { key: 'process', icon: Wrench, label: '维修工艺' },
                ].map(t => (
                  <button key={t.key} onClick={() => {
                    if (t.key === 'fault') {
                      setCaseForm({ case_type: 'fault', title: '', equipment_type: '', fault_category: '',
                        phenomenon: '', root_cause: '', troubleshooting_steps: '', preventive_measures: '',
                        severity: 'medium' })
                    } else {
                      setCaseForm({ case_type: 'process', title: '', category: '', text: '' })
                    }
                  }}
                    className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                      caseForm.case_type === t.key
                        ? 'bg-sky-100 text-sky-700 border border-sky-300'
                        : 'bg-cloud-100 text-ink-muted border border-cloud-200 hover:bg-cloud-200'
                    }`}>
                    <t.icon size={14} /> {t.label}
                  </button>
                ))}
              </div>
            )}

            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-ink-body">标题 *</label>
                <input value={caseForm.title || ''} onChange={e => setCaseForm({...caseForm, title: e.target.value})}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                  placeholder={caseForm.case_type === 'fault' ? '如：发动机怠速抖动' : '如：发动机正时皮带更换工艺'} />
              </div>

              {/* 故障案例专属表单字段 */}
              {caseForm.case_type === 'fault' && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs font-medium text-ink-body">设备类型</label>
                      <input value={caseForm.equipment_type || ''} onChange={e => setCaseForm({...caseForm, equipment_type: e.target.value})}
                        className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                        placeholder="如：发动机" />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-ink-body">故障类别</label>
                      <input value={caseForm.fault_category || ''} onChange={e => setCaseForm({...caseForm, fault_category: e.target.value})}
                        className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                        placeholder="如：机械故障" />
                    </div>
                  </div>
                  <div>
                    <label className="text-xs font-medium text-ink-body">故障现象 *</label>
                    <textarea value={caseForm.phenomenon || ''} onChange={e => setCaseForm({...caseForm, phenomenon: e.target.value})} rows={2}
                      className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                      placeholder="描述故障的表现…" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-ink-body">根本原因 *</label>
                    <input value={caseForm.root_cause || ''} onChange={e => setCaseForm({...caseForm, root_cause: e.target.value})}
                      className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                      placeholder="如：火花塞老化导致点火不良" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-ink-body">排除步骤（每行一步）</label>
                    <textarea value={caseForm.troubleshooting_steps || ''} onChange={e => setCaseForm({...caseForm, troubleshooting_steps: e.target.value})} rows={3}
                      className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400 font-mono text-xs"
                      placeholder="1. 检查火花塞状态&#10;2. 测量缸压&#10;3. …" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-ink-body">预防措施（每行一条）</label>
                    <textarea value={caseForm.preventive_measures || ''} onChange={e => setCaseForm({...caseForm, preventive_measures: e.target.value})} rows={2}
                      className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400 font-mono text-xs"
                      placeholder="1. 定期更换火花塞&#10;2. …" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-ink-body">严重程度</label>
                    <select value={caseForm.severity || 'medium'} onChange={e => setCaseForm({...caseForm, severity: e.target.value})}
                      className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400">
                      {SEVERITY_OPTIONS.map(o => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  </div>
                </>
              )}

              {/* 工艺案例专属表单字段 */}
              {caseForm.case_type === 'process' && (
                <>
                  <div>
                    <label className="text-xs font-medium text-ink-body">工艺类别</label>
                    <select value={caseForm.category || ''} onChange={e => setCaseForm({...caseForm, category: e.target.value})}
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
                    <textarea value={caseForm.text || ''} onChange={e => setCaseForm({...caseForm, text: e.target.value})} rows={8}
                      className="w-full mt-1 px-3 py-2 rounded-lg border border-cloud-300 text-sm focus:outline-none focus:border-sky-400"
                      placeholder="输入工艺文档内容，系统会自动识别类别和参数…" />
                  </div>
                </>
              )}
            </div>

            <div className="flex gap-2 mt-5 pt-4 border-t border-cloud-200">
              <button onClick={handleSaveCase} disabled={caseSaving || !caseForm.title?.trim()}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-sky-500 text-white hover:bg-sky-600 disabled:opacity-40 transition-colors">
                {caseSaving && <Loader2 size={14} className="animate-spin" />}
                {caseSaving ? '保存中…' : (editingCase ? '更新案例' : '创建案例')}
              </button>
              <button onClick={() => setCaseModalOpen(false)}
                className="px-4 py-2 rounded-lg text-sm border border-cloud-300 text-ink-muted hover:bg-cloud-200 transition-colors">取消</button>
            </div>
          </div>
        </div>
      )}

      {/* ===== 统一案例详情弹窗 ===== */}
      {viewingCase && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setViewingCase(null)} role="dialog" aria-modal="true" aria-label={`案例详情: ${viewingCase.title}`}>
          <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-ink-primary">{viewingCase.title}</h3>
                <div className="flex items-center gap-2 mt-1">
                  <span className={`badge text-2xs ${viewingCase.case_type === 'fault' ? 'badge-warning' : 'badge-info'}`}>
                    {viewingCase.case_type === 'fault' ? '故障案例' : '维修工艺'}
                  </span>
                  {viewingCase.case_type === 'fault' && (
                    <>
                      <span className={`badge text-2xs ${BADGE_COLORS[viewingCase.severity] || 'badge-info'}`}>
                        {SEVERITY_LABELS[viewingCase.severity] || viewingCase.severity || '中'}
                      </span>
                      {viewingCase.equipment_type && (
                        <span className="px-2 py-0.5 rounded-md text-2xs bg-cloud-100 text-ink-body">{viewingCase.equipment_type}</span>
                      )}
                      {viewingCase.fault_category && (
                        <span className="px-2 py-0.5 rounded-md text-2xs bg-cloud-100 text-ink-body">{viewingCase.fault_category}</span>
                      )}
                    </>
                  )}
                  {viewingCase.case_type === 'process' && (
                    <span className="badge badge-info text-2xs">{viewingCase.category}</span>
                  )}
                </div>
              </div>
              <button onClick={() => setViewingCase(null)}
                className="p-1 rounded text-ink-muted hover:text-ink-body hover:bg-cloud-100 transition-colors">
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            {/* 故障案例专属详情 */}
            {viewingCase.case_type === 'fault' && (
              <>
                <div className="mb-4">
                  <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">故障现象</h4>
                  <p className="text-sm text-ink-body bg-cloud-200 rounded-lg p-3">{viewingCase.phenomenon || '暂无描述'}</p>
                </div>
                <div className="mb-4">
                  <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">根本原因</h4>
                  <div className="p-3 rounded-lg bg-amber-50 text-sm text-amber-800 border border-amber-100">
                    {viewingCase.root_cause || '未指定'}
                  </div>
                </div>
                {viewingCase.troubleshooting_steps?.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-xs font-semibold text-sage-500 uppercase tracking-wide mb-1">
                      排除步骤 ({viewingCase.troubleshooting_steps.length} 步)
                    </h4>
                    <ol className="space-y-1.5">
                      {viewingCase.troubleshooting_steps.map((s, j) => (
                        <li key={j} className="flex gap-2 text-sm text-ink-body">
                          <span className="flex-shrink-0 w-5 h-5 rounded-full bg-sage-100 text-sage-600 text-2xs flex items-center justify-center font-medium mt-0.5">{j + 1}</span>
                          {s}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
                {viewingCase.preventive_measures?.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-xs font-semibold text-sky-500 uppercase tracking-wide mb-1">
                      预防措施 ({viewingCase.preventive_measures.length} 条)
                    </h4>
                    <ul className="space-y-1.5">
                      {viewingCase.preventive_measures.map((m, j) => (
                        <li key={j} className="flex gap-2 text-sm text-ink-body">
                          <span className="flex-shrink-0 text-sky-400 mt-0.5">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                          </span>
                          {m}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}

            {/* 工艺案例专属详情 */}
            {viewingCase.case_type === 'process' && (
              <>
                {viewingCase.parameters?.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-xs font-semibold text-sage-500 uppercase tracking-wide mb-1">
                      工艺参数 ({viewingCase.parameters.length})
                    </h4>
                    <div className="flex flex-wrap gap-1.5">
                      {viewingCase.parameters.map((pm, j) => (
                        <span key={j} className="px-2 py-0.5 rounded-md text-xs bg-sage-50 text-sage-700 border border-sage-100">
                          {pm.name}: {pm.value}{pm.unit}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                <div className="mb-4">
                  <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">文档内容</h4>
                  <div className="p-3 rounded-lg bg-cloud-200 text-sm text-ink-body whitespace-pre-wrap max-h-64 overflow-y-auto">
                    {viewingCase.full_text || viewingCase.text_preview || '暂无内容'}
                  </div>
                </div>
              </>
            )}

            {/* 操作 */}
            <div className="flex gap-2 pt-4 border-t border-cloud-200">
              {canManageCases && (
                <>
                  <button onClick={() => { const c = viewingCase; setViewingCase(null); openCaseEdit(c); }}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-sage-200 text-sage-600 hover:bg-sage-50 transition-colors">
                    <Edit3 size={14} /> 编辑
                  </button>
                  <button onClick={() => { const c = viewingCase; setViewingCase(null); handleDeleteCase(c.id, c.title); }}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-rose-200 text-rose-600 hover:bg-rose-50 transition-colors">
                    <Trash2 size={14} /> 删除
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
    </KnowledgeErrorBoundary>
  )
}
