import { useState, useEffect, useCallback } from 'react'
import {
  Search, Database, AlertTriangle, Wrench, BookOpen,
  GitBranch, ChevronRight, ArrowLeft, Tag, Layers, Filter, X, GitGraph
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '../utils/api'
import KnowledgeGraphD3 from '../components/KnowledgeGraphD3'

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

export default function ManufacturingKnowledgePage() {
  const [activeTab, setActiveTab] = useState('graph')
  const [kgNodes, setKgNodes] = useState([])
  const [kgSummary, setKgSummary] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [lineage, setLineage] = useState(null)
  const [faultResults, setFaultResults] = useState([])
  const [faultStats, setFaultStats] = useState(null)
  const [processCats, setProcessCats] = useState({})
  const [processResults, setProcessResults] = useState([])
  const [searchQ, setSearchQ] = useState('')
  const [loading, setLoading] = useState(false)

  // Load KG data
  const loadGraph = useCallback(async () => {
    setLoading(true)
    try {
      const [sumRes, nodesRes] = await Promise.all([
        api.get('/manufacturing/knowledge-graph/summary'),
        api.get('/manufacturing/knowledge-graph/nodes', { params: { limit: 200 } }),
      ])
      setKgSummary(sumRes?.data || sumRes)
      setKgNodes((nodesRes?.data || nodesRes)?.nodes || [])
    } catch (e) { /* quiet */ }
    finally { setLoading(false) }
  }, [])

  const loadFaults = useCallback(async () => {
    setLoading(true)
    try {
      const [statsRes, searchRes] = await Promise.all([
        api.get('/manufacturing/fault-cases/stats'),
        api.get('/manufacturing/fault-cases/search', { params: { q: searchQ, top_k: 50 } }),
      ])
      setFaultStats(statsRes?.data || statsRes)
      setFaultResults((searchRes?.data || searchRes)?.results || [])
    } catch (e) { /* quiet */ }
    finally { setLoading(false) }
  }, [searchQ])

  const loadProcess = useCallback(async () => {
    setLoading(true)
    try {
      const [catsRes, resultsRes] = await Promise.all([
        api.get('/manufacturing/process-library/categories'),
        api.get('/manufacturing/process-library/search', { params: { q: searchQ, limit: 50 } }),
      ])
      setProcessCats(catsRes?.data || catsRes || {})
      setProcessResults((resultsRes?.data || resultsRes)?.results || [])
    } catch (e) { /* quiet */ }
    finally { setLoading(false) }
  }, [searchQ])

  useEffect(() => {
    if (activeTab === 'graph') loadGraph()
    else if (activeTab === 'faults') loadFaults()
    else if (activeTab === 'process') loadProcess()
  }, [activeTab])

  // Search
  const handleSearch = () => {
    if (activeTab === 'faults') loadFaults()
    else if (activeTab === 'process') loadProcess()
  }

  // Node detail + lineage
  const viewNodeDetail = async (nodeId) => {
    try {
      const [detailRes, lineageRes] = await Promise.all([
        api.get(`/manufacturing/knowledge-graph/nodes/${nodeId}`),
        api.get(`/manufacturing/knowledge-graph/nodes/${nodeId}/lineage`),
      ])
      setSelectedNode((detailRes?.data || detailRes)?.node)
      setLineage(lineageRes?.data || lineageRes)
    } catch (e) { /* quiet */ }
  }

  // Node type color
  const nodeTypeColor = (type) => {
    const map = {
      knowledge_point: 'bg-coral-50 text-coral-600 border-coral-200',
      competition_topic: 'bg-sage-50 text-sage-600 border-sage-200',
      skill_point: 'bg-sky-50 text-sky-600 border-sky-200',
    }
    return map[type] || 'bg-warm-100 text-warm-600 border-warm-200'
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-warm-800 flex items-center gap-2">
            <Database size={22} className="text-sage-500" />
            知识库
          </h1>
          <p className="text-sm text-warm-500 mt-1">赛项知识图谱 · 故障案例 · 工艺文档</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-warm-100 rounded-xl w-fit">
        {TABS.map(t => (
          <button key={t.key} onClick={() => { setActiveTab(t.key); setSelectedNode(null); setLineage(null) }}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === t.key ? 'bg-white text-warm-800 shadow-sm' : 'text-warm-500 hover:text-warm-700'
            }`}>
            <t.icon size={15} /> {t.label}
          </button>
        ))}
      </div>

      {/* Search bar (faults & process) */}
      {(activeTab === 'faults' || activeTab === 'process') && (
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-warm-400" />
            <input value={searchQ} onChange={e => setSearchQ(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder={activeTab === 'faults' ? '搜索故障现象、原因…' : '搜索工艺名称、参数…'}
              className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-warm-200 text-sm bg-white
                focus:outline-none focus:border-coral-300 focus:ring-2 focus:ring-coral-50 transition-all" />
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
            {kgSummary && (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {[
                  { label: '节点总数', value: kgSummary.total_nodes, icon: Database, color: 'coral' },
                  { label: '关系总数', value: kgSummary.total_edges, icon: GitBranch, color: 'sage' },
                  { label: '节点类型', value: Object.keys(kgSummary.node_types || {}).length, icon: Layers, color: 'sky' },
                  { label: '关系类型', value: Object.keys(kgSummary.relation_types || {}).length, icon: Tag, color: 'amber' },
                ].map(s => (
                  <div key={s.label} className="card p-4">
                    <s.icon size={16} className={`text-${s.color}-400 mb-2`} />
                    <p className="text-xl font-bold text-warm-800">{s.value}</p>
                    <p className="text-xs text-warm-500">{s.label}</p>
                  </div>
                ))}
              </div>
            )}
            <KnowledgeGraphD3 onNodeClick={(node, lineage) => { setSelectedNode(node); setLineage(lineage) }} />
          </motion.div>
        )}

        {/* ========== NODE LIST TAB ========== */}
        {activeTab === 'nodes' && (
          <motion.div key="nodes" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="space-y-4">
            <div className="card p-0 overflow-hidden">
              <div className="p-4 border-b border-warm-100 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-warm-700">知识节点</h3>
                <span className="text-xs text-warm-500">{kgNodes.length} 个节点</span>
              </div>
              <div className="max-h-[420px] overflow-y-auto">
                {kgNodes.slice(0, 100).map(node => (
                  <button key={node.id} onClick={() => viewNodeDetail(node.id)}
                    className="w-full flex items-center gap-3 px-4 py-3 hover:bg-warm-50 transition-colors border-b border-warm-50 text-left">
                    <div className={`px-2 py-0.5 rounded-md text-2xs border ${nodeTypeColor(node.node_type)}`}>
                      {node.node_type === 'knowledge_point' ? '知识点' :
                       node.node_type === 'competition_topic' ? '赛题' : node.node_type}
                    </div>
                    <span className="text-sm text-warm-700 flex-1 truncate">{node.name}</span>
                    <span className="text-xs text-warm-400">Lv.{node.difficulty_level || 1}</span>
                    <ChevronRight size={14} className="text-warm-400" />
                  </button>
                ))}
              </div>
            </div>
          </motion.div>
        )}

        {/* ========== FAULT CASES TAB ========== */}
        {activeTab === 'faults' && (
          <motion.div key="faults" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="space-y-4">
            {/* Stats */}
            {faultStats && (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="card p-4">
                  <AlertTriangle size={16} className="text-amber-400 mb-2" />
                  <p className="text-xl font-bold text-warm-800">{faultStats.total_cases}</p>
                  <p className="text-xs text-warm-500">总案例数</p>
                </div>
                {faultStats.equipment_types && (
                  <div className="card p-4">
                    <Wrench size={16} className="text-sage-400 mb-2" />
                    <p className="text-xl font-bold text-warm-800">{Object.keys(faultStats.equipment_types).length}</p>
                    <p className="text-xs text-warm-500">设备类型</p>
                  </div>
                )}
                {faultStats.fault_categories && (
                  <div className="card p-4">
                    <Layers size={16} className="text-sky-400 mb-2" />
                    <p className="text-xl font-bold text-warm-800">{Object.keys(faultStats.fault_categories).length}</p>
                    <p className="text-xs text-warm-500">故障类别</p>
                  </div>
                )}
                {faultStats.severity_distribution && (
                  <div className="card p-4">
                    <AlertTriangle size={16} className="text-rose-400 mb-2" />
                    <p className="text-xl font-bold text-warm-800">
                      {faultStats.severity_distribution.critical || faultStats.severity_distribution.high || 0}
                    </p>
                    <p className="text-xs text-warm-500">高严重度</p>
                  </div>
                )}
              </div>
            )}

            {/* Case cards */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {faultResults.map((c, i) => (
                <motion.div key={c.id || i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className="card p-4 hover:shadow-warm-md transition-shadow">
                  <div className="flex items-start justify-between mb-2">
                    <h4 className="text-sm font-semibold text-warm-800">{c.title}</h4>
                    <span className={`badge text-2xs ${BADGE_COLORS[c.severity] || 'badge-info'}`}>
                      {c.severity || 'medium'}
                    </span>
                  </div>
                  <p className="text-xs text-warm-600 mb-3 line-clamp-2">{c.phenomenon}</p>
                  <div className="flex flex-wrap gap-1.5 mb-3">
                    <span className="px-2 py-0.5 rounded-md text-2xs bg-warm-100 text-warm-600">
                      {c.equipment_type}
                    </span>
                    <span className="px-2 py-0.5 rounded-md text-2xs bg-warm-100 text-warm-600">
                      {c.fault_category}
                    </span>
                    {c.score && (
                      <span className="px-2 py-0.5 rounded-md text-2xs bg-coral-50 text-coral-600">
                        匹配 {(c.score * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  {c.root_cause && (
                    <div className="p-2 rounded-lg bg-warm-50 text-xs text-warm-700">
                      <span className="font-medium text-amber-600">根因：</span>{c.root_cause}
                    </div>
                  )}
                  {c.troubleshooting_steps?.length > 0 && (
                    <details className="mt-2">
                      <summary className="text-xs text-sage-600 cursor-pointer font-medium">排除步骤 ({c.troubleshooting_steps.length} 步)</summary>
                      <ol className="mt-1 pl-4 text-xs text-warm-600 space-y-0.5 list-decimal">
                        {c.troubleshooting_steps.map((s, j) => <li key={j}>{s}</li>)}
                      </ol>
                    </details>
                  )}
                </motion.div>
              ))}
            </div>
            {faultResults.length === 0 && (
              <p className="text-center text-sm text-warm-400 py-12">暂无故障案例数据</p>
            )}
          </motion.div>
        )}

        {/* ========== PROCESS LIBRARY TAB ========== */}
        {activeTab === 'process' && (
          <motion.div key="process" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="space-y-4">
            {/* Category stats */}
            {Object.keys(processCats).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(processCats).map(([cat, count]) => (
                  <div key={cat} className="px-3 py-1.5 rounded-lg bg-warm-100 text-xs font-medium text-warm-600">
                    {cat}: <span className="text-warm-800">{count}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Process cards */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {processResults.map((p, i) => (
                <motion.div key={p.id || i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className="card p-4 hover:shadow-warm-md transition-shadow">
                  <div className="flex items-start justify-between mb-2">
                    <h4 className="text-sm font-semibold text-warm-800">{p.title}</h4>
                    <span className="badge badge-info text-2xs">{p.category}</span>
                  </div>
                  <p className="text-xs text-warm-500 mb-3 line-clamp-2">{p.text_preview}</p>
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
            {processResults.length === 0 && (
              <p className="text-center text-sm text-warm-400 py-12">暂无工艺文档数据</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
