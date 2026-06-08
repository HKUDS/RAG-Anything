import { useState, useEffect, useRef, useCallback } from 'react'
import { Search, Eye, Trash2, X, FileText, Hash, Clock, Filter, ZoomIn, ZoomOut, RotateCcw } from 'lucide-react'
import * as d3 from 'd3'
import { api } from '../utils/api'

const STATUS = { processed: 'badge-success', processing: 'badge-warning', handling: 'badge-info', failed: 'badge-error' }
const STATUS_CN = { processed: '已完成', processing: '处理中', handling: '入库中', failed: '失败' }
const NODE_COLORS = ['#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#ef4444', '#06b6d4', '#f97316']

export default function KnowledgePage() {
  const [docs, setDocs] = useState([])
  const [entities, setEntities] = useState([])
  const [stats, setStats] = useState({})
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [filter, setFilter] = useState('')
  const [graphSearch, setGraphSearch] = useState('')
  const [detailDoc, setDetailDoc] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [selectedNode, setSelectedNode] = useState(null)
  const [nodeDetails, setNodeDetails] = useState(null)
  const svgRef = useRef()
  const graphContainerRef = useRef()
  const zoomRef = useRef(null)

  const loadData = () => {
    api.getDocuments().then(r => setDocs(r.documents || [])).catch(() => {})
    api.getStats().then(setStats).catch(() => {})
    api.getEntities(200).then(r => setEntities(r.entities || [])).catch(() => {})
    api.getGraph().then(r => {
      // Calculate degree for each node
      const degree = {}
      ;(r.edges || []).forEach(e => {
        degree[e.source] = (degree[e.source] || 0) + 1
        degree[e.target] = (degree[e.target] || 0) + 1
      })
      // Add degree to nodes, sort by degree
      const nodes = (r.nodes || []).map(n => ({ ...n, degree: degree[n.id] || 0 }))
      nodes.sort((a, b) => b.degree - a.degree)
      setGraph({ nodes, edges: r.edges || [] })
    }).catch(() => {})
  }

  useEffect(() => {
    loadData()
    const timer = setInterval(loadData, 8000)
    return () => clearInterval(timer)
  }, [])

  // D3 interactive graph with labels
  const drawGraph = useCallback(() => {
    if (!svgRef.current || !graph.nodes.length) return
    try {
      const svg = d3.select(svgRef.current)
      svg.selectAll('*').remove()

      // Show top N nodes by degree, or search-filtered
      let displayNodes = [...graph.nodes]
      if (graphSearch.trim()) {
        const q = graphSearch.toLowerCase()
        displayNodes = displayNodes.filter(n => n.label?.toLowerCase().includes(q) || n.id?.toLowerCase().includes(q))
        // Include connected nodes
        const matchedIds = new Set(displayNodes.map(n => n.id))
        graph.edges.forEach(e => {
          if (matchedIds.has(e.source) && !matchedIds.has(e.target)) {
            const n = graph.nodes.find(x => x.id === e.target)
            if (n) { displayNodes.push(n); matchedIds.add(n.id) }
          }
          if (matchedIds.has(e.target) && !matchedIds.has(e.source)) {
            const n = graph.nodes.find(x => x.id === e.source)
            if (n) { displayNodes.push(n); matchedIds.add(n.id) }
          }
        })
      } else {
        displayNodes = displayNodes.slice(0, 60)
      }
      const displayIds = new Set(displayNodes.map(n => n.id))
      const displayEdges = graph.edges.filter(e => displayIds.has(e.source) && displayIds.has(e.target))

      const W = graphContainerRef.current?.clientWidth || 600
      const H = 420

      const svgEl = svg.attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%').attr('height', H)

      // Zoom
      const g = svgEl.append('g')
      const zoom = d3.zoom().scaleExtent([0.3, 4]).on('zoom', (e) => g.attr('transform', e.transform))
      svgEl.call(zoom)
      zoomRef.current = zoom

      // Color scale
      const colorScale = d3.scaleOrdinal(NODE_COLORS)

      // Size scale based on degree
      const sizeScale = d3.scaleSqrt().domain([0, d3.max(displayNodes, d => d.degree) || 1]).range([5, 18])

      const sim = d3.forceSimulation(displayNodes)
        .force('link', d3.forceLink(displayEdges).id(d => d.id).distance(d => 80 / Math.sqrt((d.source.degree || 1) + 1)))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(W / 2, H / 2))
        .force('collision', d3.forceCollide().radius(d => sizeScale(d.degree) + 8))

      // Edges
      const link = g.append('g').selectAll('line').data(displayEdges).join('line')
        .attr('stroke', '#334155').attr('stroke-width', 0.5).attr('stroke-opacity', 0.6)

      // Edge labels (only for top edges)
      const edgeLabels = g.append('g').selectAll('text').data(displayEdges.slice(0, 15)).join('text')
        .text(d => (d.label || '').slice(0, 10))
        .attr('font-size', 7).attr('fill', '#64748b').attr('text-anchor', 'middle')

      // Nodes
      const nodeGroup = g.append('g').selectAll('g').data(displayNodes).join('g')
        .attr('cursor', 'pointer')
        .call(d3.drag().on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
          .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
          .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null }))

      nodeGroup.append('circle')
        .attr('r', d => sizeScale(d.degree))
        .attr('fill', d => colorScale(d.id))
        .attr('stroke', '#1e293b').attr('stroke-width', 1)
        .attr('opacity', 0.85)

      // Labels on nodes with degree >= 2
      nodeGroup.filter(d => d.degree >= 2 || displayNodes.length <= 20)
        .append('text')
        .text(d => (d.label || d.id || '').slice(0, 10))
        .attr('font-size', d => Math.max(7, Math.min(11, sizeScale(d.degree) * 0.7)))
        .attr('fill', '#cbd5e1')
        .attr('text-anchor', 'middle')
        .attr('dy', d => sizeScale(d.degree) + 12)
        .attr('font-family', "'Microsoft YaHei', 'SimHei', sans-serif")

      // Click handler
      nodeGroup.on('click', async (e, d) => {
        e.stopPropagation()
        setSelectedNode(d)
        // Find ALL connections from full graph data (not just displayed edges)
        const connections = graph.edges.filter(e => e.source === d.id || e.target === d.id)
        // Build connected nodes: use entity names from edges, plus look up in nodes array
        const connectedNames = new Set()
        const connectionList = []
        connections.forEach(e => {
          const other = e.source === d.id ? e.target : e.source
          connectedNames.add(other)
          connectionList.push({ other, label: e.label || '', direction: e.source === d.id ? '→' : '←' })
        })
        // Try to find matching nodes, but also accept entity names not in node list
        const connectedNodes = graph.nodes.filter(n => connectedNames.has(n.id))
        setNodeDetails({
          node: d,
          connections: connectionList.slice(0, 30),
          connectedNodes: connectedNodes.slice(0, 20),
          totalConnections: connectionList.length,
        })
      })

      // Click background to deselect
      svgEl.on('click', () => { setSelectedNode(null); setNodeDetails(null) })

      // Highlight selected node
      if (selectedNode) {
        nodeGroup.select('circle')
          .attr('opacity', d => d.id === selectedNode.id ? 1 : 0.3)
        link.attr('stroke-opacity', d =>
          d.source.id === selectedNode.id || d.target.id === selectedNode.id ? 0.9 : 0.15)
      }

      sim.on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
        edgeLabels.attr('x', d => (d.source.x + d.target.x) / 2)
                  .attr('y', d => (d.source.y + d.target.y) / 2)
        nodeGroup.attr('transform', d => `translate(${d.x},${d.y})`)
      })

      return () => sim.stop()
    } catch(e) { console.warn('D3 error:', e) }
  }, [graph, graphSearch, selectedNode])

  useEffect(() => { return drawGraph() }, [drawGraph])

  const handleZoom = (dir) => {
    if (!svgRef.current) return
    const svg = d3.select(svgRef.current)
    if (dir === 'in') svg.transition().call(zoomRef.current.scaleBy, 1.5)
    else if (dir === 'out') svg.transition().call(zoomRef.current.scaleBy, 0.7)
    else svg.transition().call(zoomRef.current.transform, d3.zoomIdentity)
  }

  const filteredDocs = docs.filter(d => d.file?.toLowerCase().includes(filter.toLowerCase()))

  const handleDelete = async () => {
    if (!deleteConfirm) return
    setDeleting(true)
    try {
      await api.deleteDocument(deleteConfirm.id)
      setDeleteConfirm(null)
      loadData()
    } catch(e) { alert('删除失败: ' + e.message) }
    setDeleting(false)
  }

  const toggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredDocs.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredDocs.map(d => d.id)))
    }
  }

  const handleBatchDelete = async () => {
    setBatchDeleting(true)
    try {
      const ids = [...selectedIds]
      const res = await api.deleteDocuments(ids)
      setSelectedIds(new Set())
      loadData()
      const msg = `已删除 ${res.total_deleted} 个文档`
      if (res.not_found?.length) alert(msg + `，${res.not_found.length} 个未找到`)
      else if (res.errors?.length) alert(msg + `，${res.errors.length} 个失败`)
      // try the parent toast if available
    } catch(e) { alert('批量删除失败: ' + e.message) }
    setBatchDeleting(false)
  }

  return (
    <div className="space-y-6">
      <h2 className="font-display text-xl font-bold text-slate-100">知识库管理</h2>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        {[{ label: '文档总数', val: stats.documents || 0, color: 'text-neon-400' },
          { label: '实体总数', val: stats.entities || 0, color: 'text-emerald-400' },
          { label: '关系总数', val: stats.relations || 0, color: 'text-amber-400' },
          { label: '分块总数', val: stats.chunks || 0, color: 'text-purple-400' }]
          .map(({ label, val, color }) => (
            <div key={label} className="glass p-4">
              <p className="text-xs text-slate-500">{label}</p>
              <p className={`text-2xl font-display font-bold mt-1 ${color}`}>{val}</p>
            </div>
          ))}
      </div>

      {/* Document Table */}
      <div className="glass p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-medium text-slate-300">文档列表</h3>
            {selectedIds.size > 0 && (
              <button
                className="flex items-center gap-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-400 border border-red-500/30 text-xs py-1.5 px-3 rounded-lg transition-colors"
                onClick={handleBatchDelete} disabled={batchDeleting}
              >
                <Trash2 size={12} />
                {batchDeleting ? '删除中…' : `删除选中 (${selectedIds.size})`}
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Search size={14} className="text-slate-500"/>
            <input className="input-field text-xs w-48 py-1.5" placeholder="搜索文档…" value={filter}
              onChange={e => setFilter(e.target.value)} />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50 text-left text-xs text-slate-500">
                <th className="pb-2 font-medium w-8">
                  <input type="checkbox" checked={selectedIds.size > 0 && selectedIds.size === filteredDocs.length}
                    onChange={toggleSelectAll} className="w-3.5 h-3.5" />
                </th>
                <th className="pb-2 font-medium">文件名</th><th className="pb-2 font-medium">状态</th>
                <th className="pb-2 font-medium">分块</th><th className="pb-2 font-medium">字数</th>
                <th className="pb-2 font-medium">更新时间</th><th className="pb-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredDocs.map(doc => (
                <tr key={doc.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                  <td className="py-2.5">
                    <input type="checkbox" checked={selectedIds.has(doc.id)}
                      onChange={() => toggleSelect(doc.id)} className="w-3.5 h-3.5" />
                  </td>
                  <td className="py-2.5 text-slate-300 max-w-40 truncate" title={doc.file}>{doc.file}</td>
                  <td className="py-2.5"><span className={STATUS[doc.status] || 'badge-info'}>{STATUS_CN[doc.status] || doc.status}</span></td>
                  <td className="py-2.5 font-mono text-slate-400">{doc.chunks}</td>
                  <td className="py-2.5 font-mono text-slate-400">{(doc.length || 0).toLocaleString()}</td>
                  <td className="py-2.5 text-xs text-slate-500">{doc.updated?.slice(0, 16) || '-'}</td>
                  <td className="py-2.5 flex gap-1">
                    <button className="btn-ghost text-xs py-1 px-2" onClick={() => setDetailDoc(doc)} title="详情"><Eye size={14}/></button>
                    <button className="btn-ghost text-xs py-1 px-2 text-red-400 hover:text-red-300" onClick={() => setDeleteConfirm(doc)} title="删除"><Trash2 size={14}/></button>
                  </td>
                </tr>
              ))}
              {filteredDocs.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-slate-500">暂无文档，去「上传」页面添加</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Knowledge Graph */}
      <div className="glass p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-slate-300 flex items-center gap-2">
            <Filter size={14}/>知识图谱
            <span className="text-[10px] text-slate-600 font-normal">
              {graph.nodes.length} 节点 · {graph.edges.length} 边
              {graphSearch ? ` · 搜索: "${graphSearch}"` : ' · 显示前60个核心节点'}
            </span>
          </h3>
          <div className="flex items-center gap-2">
            <input className="input-field text-xs w-36 py-1.5" placeholder="搜索实体…" value={graphSearch}
              onChange={e => setGraphSearch(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && drawGraph()} />
            <button className="btn-ghost p-1.5" onClick={() => handleZoom('in')} title="放大"><ZoomIn size={14}/></button>
            <button className="btn-ghost p-1.5" onClick={() => handleZoom('out')} title="缩小"><ZoomOut size={14}/></button>
            <button className="btn-ghost p-1.5" onClick={() => handleZoom('reset')} title="重置"><RotateCcw size={14}/></button>
          </div>
        </div>
        <div ref={graphContainerRef} className="relative">
          <svg ref={svgRef} className="w-full bg-ink-900/50 rounded-lg cursor-grab active:cursor-grabbing" style={{ minHeight: 420 }} />
          {selectedNode && (
            <div className="absolute top-2 left-2 bg-ink-800/95 border border-slate-700 rounded-lg p-2 text-xs max-w-48">
              <p className="text-slate-300 font-medium truncate">{selectedNode.label || selectedNode.id}</p>
              <p className="text-slate-500">关联: {selectedNode.degree} 条边</p>
              <p className="text-[10px] text-slate-600 mt-1">点击空白取消选中</p>
            </div>
          )}
        </div>
        <div className="flex items-center gap-4 text-[10px] text-slate-600">
          <span>💡 节点越大 = 关联越多 | 拖拽移动 | 滚轮缩放 | 点击查看详情</span>
        </div>
      </div>

      {/* Node Detail + Entity List Row */}
      <div className="grid grid-cols-2 gap-4">
        {/* Entity detail on click */}
        <div className="glass p-4 space-y-3">
          <h3 className="text-sm font-medium text-slate-300">
            {nodeDetails ? `"${nodeDetails.node.label || nodeDetails.node.id}" 的关联` : '点击图谱节点查看关联'}
          </h3>
          {nodeDetails ? (
            <div className="space-y-2 max-h-80 overflow-y-auto">
              <p className="text-xs text-slate-500">
                共 {nodeDetails.totalConnections} 条关系，显示前 {nodeDetails.connections.length} 条
              </p>
              {nodeDetails.connections.map(function(c, i) {
                return (
                  <div key={i} className="flex items-center gap-2 px-3 py-1.5 rounded bg-ink-900/40 text-xs">
                    <span className="text-neon-400 font-mono shrink-0">{c.direction}</span>
                    <span className="text-slate-400 truncate flex-1">{c.other}</span>
                    {c.label && <span className="text-[10px] text-slate-600 shrink-0">{c.label.slice(0, 15)}</span>}
                  </div>
                );
              })}
              {nodeDetails.connectedNodes.length > 0 && (
                <div className="mt-3">
                  <p className="text-[10px] text-slate-500 mb-1">关联实体:</p>
                  <div className="flex flex-wrap gap-1">
                    {nodeDetails.connectedNodes.map(function(n) { return (
                      <span key={n.id} className="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-400">{n.label || n.id}</span>
                    ); })}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-slate-600 py-8 text-center">点击知识图谱中的节点查看该实体的详细关联关系</p>
          )}
        </div>

        {/* Entity list */}
        <div className="glass p-4 space-y-3">
          <h3 className="text-sm font-medium text-slate-300">全部实体 ({entities.length})</h3>
          <div className="space-y-1 max-h-80 overflow-y-auto">
            {entities.slice(0, 100).map((e, i) => (
              <div key={e.id || i} className="px-3 py-1.5 rounded bg-ink-900/30 text-xs flex items-center justify-between hover:bg-ink-800/50 cursor-pointer"
                onClick={() => {
                  let node = graph.nodes.find(n => n.id === e.name)
                  if (!node) node = { id: e.name, label: e.name, degree: 0 }
                  setGraphSearch(e.name)
                  setSelectedNode(node)
                  const connections = graph.edges.filter(ed => ed.source === node.id || ed.target === node.id)
                  const connectionList = connections.map(ed => ({
                    other: ed.source === node.id ? ed.target : ed.source,
                    label: ed.label || '',
                    direction: ed.source === node.id ? '→' : '←',
                  }))
                  const connectedNames = new Set(connectionList.map(c => c.other))
                  setNodeDetails({
                    node,
                    connections: connectionList.slice(0, 30),
                    connectedNodes: graph.nodes.filter(n => connectedNames.has(n.id)).slice(0, 20),
                    totalConnections: connectionList.length,
                  })
                }}>
                <span className="text-slate-300 truncate flex-1">{e.name}</span>
                {e.type && <span className="text-[10px] text-slate-600 ml-2">{e.type}</span>}
              </div>
            ))}
            {entities.length === 0 && <p className="text-xs text-slate-600 py-4 text-center">暂无实体数据</p>}
          </div>
        </div>
      </div>

      {/* Document Detail Drawer */}
      {detailDoc && (
        <div className="fixed inset-0 z-50 flex justify-end" onClick={() => setDetailDoc(null)}>
          <div className="absolute inset-0 bg-black/50" />
          <div className="relative w-96 glass m-3 p-6 overflow-y-auto animate-slide-in" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display font-bold text-slate-100">文档详情</h3>
              <button className="btn-ghost p-1" onClick={() => setDetailDoc(null)}><X size={16}/></button>
            </div>
            <div className="space-y-3 text-sm">
              {[{ icon: FileText, label: '文件名', val: detailDoc.file },
                { icon: Hash, label: '状态', val: STATUS_CN[detailDoc.status] || detailDoc.status },
                { icon: Hash, label: '分块数', val: detailDoc.chunks },
                { icon: FileText, label: '字数', val: (detailDoc.length || 0).toLocaleString() },
                { icon: Clock, label: '创建时间', val: detailDoc.created?.slice(0, 19) || '-' },
                { icon: Clock, label: '更新时间', val: detailDoc.updated?.slice(0, 19) || '-' }]
                .map(({ icon: Icon, label, val }) => (
                  <div key={label} className="flex items-center gap-3">
                    <Icon size={14} className="text-slate-600 shrink-0"/>
                    <span className="text-slate-500 w-16 shrink-0">{label}</span>
                    <span className="text-slate-300 truncate">{val}</span>
                  </div>
                ))}
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setDeleteConfirm(null)}>
          <div className="absolute inset-0 bg-black/60" />
          <div className="relative glass p-6 w-80 text-center" onClick={e => e.stopPropagation()}>
            <Trash2 size={32} className="mx-auto mb-3 text-red-400"/>
            <p className="text-slate-200 font-medium mb-1">确认删除</p>
            <p className="text-xs text-slate-500 mb-4 truncate">{deleteConfirm.file}</p>
            <p className="text-xs text-amber-400 mb-4">删除后将清除该文档的所有实体、关系和向量数据</p>
            <div className="flex gap-3 justify-center">
              <button className="btn-ghost text-sm" onClick={() => setDeleteConfirm(null)}>取消</button>
              <button className="bg-red-500 hover:bg-red-600 text-white text-sm px-4 py-2 rounded-lg" onClick={handleDelete} disabled={deleting}>
                {deleting ? '删除中…' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
