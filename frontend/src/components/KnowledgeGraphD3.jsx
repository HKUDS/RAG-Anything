import { useEffect, useRef, useState, useCallback } from 'react'
import * as d3 from 'd3'
import { ZoomIn, ZoomOut, RotateCcw, X } from 'lucide-react'
import { api } from '../utils/api'

const COLORS = {
  knowledge_point: '#e8734a', competition_topic: '#5b9bd5',
  skill_point: '#6b9e7a', default: '#d4a853',
}
const LINE_STYLES = { requires: '4,2', advances_to: '', related_to: '2,2' }

export default function KnowledgeGraphD3({ onNodeClick }) {
  const svgRef = useRef()
  const [selectedNode, setSelectedNode] = useState(null)
  const [lineage, setLineage] = useState(null)
  const [loading, setLoading] = useState(true)

  const loadGraph = useCallback(async () => {
    try {
      const [nodesRes, edgesRes] = await Promise.all([
        api.get('/manufacturing/knowledge-graph/nodes', { params: { limit: 200 } }),
        api.get('/manufacturing/knowledge-graph/nodes/edges'),
      ])
      const nodes = nodesRes?.nodes || []
      const edges = edgesRes?.edges || []
      renderGraph(nodes, edges)
    } catch (e) { /* quiet */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { loadGraph() }, [loadGraph])

  const renderGraph = (nodes, edges) => {
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    const W = svgRef.current.clientWidth || 700
    const H = 450

    const g = svg.append('g')
    const zoom = d3.zoom().scaleExtent([0.2, 4]).on('zoom', (e) => g.attr('transform', e.transform))
    svg.call(zoom)

    const sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id).distance(80))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide(25))

    const link = g.append('g').selectAll('line').data(edges).join('line')
      .attr('stroke', '#d4d4d8').attr('stroke-width', 1.5)
      .attr('stroke-dasharray', d => LINE_STYLES[d.relation_type] || '')

    const node = g.append('g').selectAll('g').data(nodes).join('g')
      .attr('cursor', 'pointer')
      .call(d3.drag().on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
        .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null }))

    node.append('circle').attr('r', 8)
      .attr('fill', d => COLORS[d.node_type] || COLORS.default)
      .attr('stroke', '#fff').attr('stroke-width', 2)

    node.append('text').text(d => d.name?.slice(0, 8))
      .attr('x', 12).attr('y', 4).attr('font-size', 10).attr('fill', '#5f6570')

    node.on('click', async (e, d) => {
      e.stopPropagation()
      setSelectedNode(d)
      try {
        const res = await api.get(`/manufacturing/knowledge-graph/nodes/${d.id}/lineage`)
        setLineage(res)
        onNodeClick?.(d, res)
      } catch { setLineage(null) }
    })

    sim.on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })
  }

  const nodeTypeLabel = t => ({ knowledge_point: '知识点', competition_topic: '赛题', skill_point: '技能' }[t] || t)

  return (
    <div className="relative">
      {loading && <div className="text-center py-8 text-sm text-warm-400">加载图谱…</div>}
      <div className="flex items-center gap-1 mb-3">
        {Object.entries(COLORS).map(([k, c]) => (
          <div key={k} className="flex items-center gap-1 text-2xs text-warm-500">
            <div className="w-3 h-3 rounded-full" style={{ background: c }} />
            {nodeTypeLabel(k)}
          </div>
        ))}
        <div className="flex-1" />
        <button onClick={() => {}} className="p-1.5 rounded-lg hover:bg-warm-100 text-warm-500">
          <ZoomIn size={14} />
        </button>
        <button onClick={() => {}} className="p-1.5 rounded-lg hover:bg-warm-100 text-warm-500">
          <RotateCcw size={14} />
        </button>
      </div>

      <svg ref={svgRef} className="w-full rounded-xl border border-warm-200 bg-warm-50" style={{ height: 450 }} />

      {/* Node detail sidebar */}
      {selectedNode && (
        <div className="mt-4 card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-warm-700">{selectedNode.name}</h4>
            <button onClick={() => setSelectedNode(null)} className="text-warm-400 hover:text-warm-600"><X size={16} /></button>
          </div>
          <p className="text-xs text-warm-600">{selectedNode.description || '暂无描述'}</p>
          {lineage && (
            <div className="grid grid-cols-3 gap-3 pt-2 border-t border-warm-100">
              <div className="p-2 rounded-lg bg-amber-50 text-xs">
                <p className="font-medium text-amber-700 mb-1">前置 ({lineage.prerequisite_count})</p>
                {lineage.prerequisites?.map(p => <div key={p.id} className="text-amber-800">• {p.name}</div>)}
              </div>
              <div className="p-2 rounded-lg bg-coral-50 text-xs text-center">当前</div>
              <div className="p-2 rounded-lg bg-sage-50 text-xs">
                <p className="font-medium text-sage-700 mb-1">进阶 ({lineage.advancement_count})</p>
                {lineage.advancements?.map(a => <div key={a.id} className="text-sage-800">• {a.name}</div>)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
