import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import * as d3 from 'd3'
import {
  ZoomIn, ZoomOut, RotateCcw, Search, X, AlertCircle,
  Loader2, Filter, Database
} from 'lucide-react'

const COLORS = {
  knowledge_point: '#e8734a', competition_topic: '#5b9bd5',
  skill_point: '#6b9e7a', default: '#d4a853',
}
const LINE_STYLES = { requires: '4,2', advances_to: '', related_to: '2,2', evaluates: '6,3', applies_in: '1,3' }
const RELATION_LABELS = { requires: '前置', advances_to: '进阶', related_to: '相关', evaluates: '评分', applies_in: '应用' }
const NODE_TYPE_LABEL = {
  knowledge_point: '知识点', competition_topic: '赛题', skill_point: '技能',
}

const SELECTED_GLOW_ID = 'selected-node-glow'

export default function KnowledgeGraphD3({
  nodes: rawNodes = [],
  edges: rawEdges = [],
  loading = false,
  error = null,
  summary = null,
  onRetry,
  onNodeClick,
}) {
  const svgRef = useRef()
  const containerRef = useRef()
  const zoomRef = useRef(null)
  const initialTransform = useRef(null)
  const simRef = useRef(null)
  const renderRef = useRef(0) // track renders for cleanup
  const selectedNodeIdRef = useRef(null) // always-current ref to avoid stale closure

  const [selectedNodeId, setSelectedNodeId] = useState(null)
  // Keep ref in sync — used by D3 effect to avoid stale closure
  selectedNodeIdRef.current = selectedNodeId
  const [tooltip, setTooltip] = useState(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  // ---- Stable references for data to avoid re-renders breaking D3 ----
  const nodes = useMemo(() => rawNodes.map(n => ({ ...n })), [rawNodes])
  const edges = useMemo(() => rawEdges.map(e => {
    const sid = e.source_id ?? e.source?.id ?? e.source
    const tid = e.target_id ?? e.target?.id ?? e.target
    return { ...e, source: sid, target: tid }
  }), [rawEdges])

  const hasData = nodes.length > 0
  const nodeTypeLabel = t => NODE_TYPE_LABEL[t] || t

  // ---- Filter nodes by search term and type ----
  const filteredNodes = useMemo(() => {
    let result = nodes
    if (searchTerm.trim()) {
      const term = searchTerm.trim().toLowerCase()
      result = result.filter(n => n.name?.toLowerCase().includes(term))
    }
    if (typeFilter) {
      result = result.filter(n => n.node_type === typeFilter)
    }
    return result
  }, [nodes, searchTerm, typeFilter])

  const filteredNodeIds = useMemo(() => new Set(filteredNodes.map(n => n.id)), [filteredNodes])

  // Filter edges to only include those where both ends are in filtered nodes.
  // ALWAYS apply this filter — not just when search/filter is active — to prevent
  // D3 "node not found" errors when edges reference nodes outside the loaded set.
  const filteredEdges = useMemo(() => {
    return edges.filter(e => {
      const sid = typeof e.source === 'object' ? e.source.id : e.source
      const tid = typeof e.target === 'object' ? e.target.id : e.target
      return filteredNodeIds.has(sid) && filteredNodeIds.has(tid)
    })
  }, [edges, filteredNodeIds])

  // ---- Node types present in data ----
  const presentNodeTypes = useMemo(() => {
    const types = new Set(nodes.map(n => n.node_type).filter(Boolean))
    return [...types]
  }, [nodes])

  // ---- Zoom handlers ----
  const handleZoomIn = useCallback(() => {
    const svg = d3.select(svgRef.current)
    if (!svg.empty() && zoomRef.current) {
      svg.transition().duration(300).call(zoomRef.current.scaleBy, 1.5)
    }
  }, [])

  const handleZoomOut = useCallback(() => {
    const svg = d3.select(svgRef.current)
    if (!svg.empty() && zoomRef.current) {
      svg.transition().duration(300).call(zoomRef.current.scaleBy, 0.67)
    }
  }, [])

  const handleReset = useCallback(() => {
    const svg = d3.select(svgRef.current)
    if (!svg.empty() && zoomRef.current && initialTransform.current) {
      svg.transition().duration(500).call(zoomRef.current.transform, initialTransform.current)
    }
  }, [])

  // ---- Cleanup simulation on unmount ----
  useEffect(() => {
    return () => {
      if (simRef.current) simRef.current.stop()
    }
  }, [])

  // ---- ResizeObserver for responsive SVG ----
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    // Guard: ResizeObserver may not exist in older browsers / embedded WebViews
    if (typeof ResizeObserver === 'undefined') return
    let ro
    try {
      ro = new ResizeObserver(() => {
        const svg = d3.select(svgRef.current)
        if (svg.empty()) return
        const w = container.clientWidth
        const h = Math.max(350, container.clientHeight || 450)
        svg.attr('width', w).attr('height', h)
      })
      ro.observe(container)
    } catch (e) {
      // ResizeObserver constructor or observe() may throw in restricted environments
      return
    }
    return () => { if (ro) ro.disconnect() }
  }, [])

  // ---- Clear selection on Escape ----
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') setSelectedNodeId(null) }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // ---- D3 rendering ----
  useEffect(() => {
    if (loading || !hasData) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    // Bump render counter for cleanup tracking
    renderRef.current += 1
    const renderId = renderRef.current

    const containerW = containerRef.current?.clientWidth || 700
    const W = containerW
    const H = Math.max(350, containerRef.current?.clientHeight || 450)

    svg.attr('width', W).attr('height', H)

    // ---- SVG defs ----
    const defs = svg.append('defs')

    // Drop shadow for drag
    const dragFilter = defs.append('filter').attr('id', `drag-shadow-${renderId}`)
      .attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%')
    dragFilter.append('feDropShadow').attr('dx', 1).attr('dy', 2)
      .attr('stdDeviation', 2).attr('flood-opacity', 0.3)

    // Glow filter for selected node
    const glowFilter = defs.append('filter').attr('id', SELECTED_GLOW_ID)
      .attr('x', '-100%').attr('y', '-100%').attr('width', '300%').attr('height', '300%')
    glowFilter.append('feGaussianBlur').attr('in', 'SourceGraphic')
      .attr('stdDeviation', 3).attr('result', 'blur')
    const merge = glowFilter.append('feMerge')
    merge.append('feMergeNode').attr('in', 'blur')
    merge.append('feMergeNode').attr('in', 'blur')
    merge.append('feMergeNode').attr('in', 'SourceGraphic')

    // ---- Main group + zoom ----
    const g = svg.append('g')
    const zoom = d3.zoom()
      .scaleExtent([0.2, 4])
      .filter((event) => {
        // Allow wheel/dblclick zoom anywhere; only allow mouse-pan on SVG background
        if (event.type === 'wheel' || event.type === 'dblclick') return true
        return event.target === svgRef.current
      })
      .on('zoom', (e) => g.attr('transform', e.transform))
    svg.call(zoom)
    zoomRef.current = zoom
    initialTransform.current = null

    // ---- Force simulation ----
    const simNodes = filteredNodes.map(n => ({ ...n }))
    const simEdges = filteredEdges.map(e => ({
      ...e,
      source: e.source?.id ?? e.source,
      target: e.target?.id ?? e.target,
    }))

    const sim = d3.forceSimulation(simNodes)
      .force('link', d3.forceLink(simEdges).id(d => d.id).distance(80))
      .force('charge', d3.forceManyBody().strength(-150))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide(22))
      .alphaDecay(0.03)
      .alphaMin(0.05)
      .velocityDecay(0.35)

    simRef.current = sim

    // ---- Build adjacency map ----
    const adjacency = new Map()
    const connectedEdges = new Map()
    simEdges.forEach((e, i) => {
      const sid = e.source?.id ?? e.source
      const tid = e.target?.id ?? e.target
      if (!adjacency.has(sid)) adjacency.set(sid, new Set())
      if (!adjacency.has(tid)) adjacency.set(tid, new Set())
      adjacency.get(sid).add(tid)
      adjacency.get(tid).add(sid)
      if (!connectedEdges.has(sid)) connectedEdges.set(sid, new Set())
      if (!connectedEdges.has(tid)) connectedEdges.set(tid, new Set())
      connectedEdges.get(sid).add(i)
      connectedEdges.get(tid).add(i)
    })

    // ---- Links ----
    const link = g.append('g').selectAll('line').data(simEdges).join('line')
      .attr('stroke', '#d4d4d8').attr('stroke-width', 1.5)
      .attr('stroke-dasharray', d => LINE_STYLES[d.relation_type] || '')

    // ---- Node groups ----
    const node = g.append('g').selectAll('g').data(simNodes).join('g')
      .attr('cursor', 'pointer')

    // Drag behavior
    const dragHandler = d3.drag()
      .on('start', function (e, d) {
        if (!e.active) sim.alphaTarget(0.3).restart()
        d.fx = d.x; d.fy = d.y
        d3.select(this).select('circle')
          .transition().duration(100)
          .attr('r', 10.4).attr('filter', `url(#drag-shadow-${renderId})`)
      })
      .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
      .on('end', function (e, d) {
        sim.alphaTarget(0)
        d.fx = null; d.fy = null
        d3.select(this).select('circle')
          .transition().duration(200)
          .attr('r', 8).attr('filter', null)
      })

    node.call(dragHandler)

    // Node circles
    node.append('circle').attr('r', 8)
      .attr('fill', d => COLORS[d.node_type] || COLORS.default)
      .attr('stroke', '#fff').attr('stroke-width', 2)

    // Node labels (12 chars max, better than 8)
    node.append('text').text(d => {
      const name = d.name || ''
      return name.length > 12 ? name.slice(0, 11) + '…' : name
    })
      .attr('x', 12).attr('y', 4).attr('font-size', 10)
      .attr('fill', '#5f6570').attr('pointer-events', 'none')

    // ---- Selection highlight (uses ref to avoid stale closure) ----
    const updateSelectionHighlight = () => {
      const sid = selectedNodeIdRef.current
      node.selectAll('circle')
        .attr('stroke', d => d.id === sid ? '#f59e0b' : '#fff')
        .attr('stroke-width', d => d.id === sid ? 3 : 2)
        .attr('filter', d => d.id === sid ? `url(#${SELECTED_GLOW_ID})` : null)
      node.selectAll('text')
        .attr('font-weight', d => d.id === sid ? '700' : '400')
        .attr('fill', d => d.id === sid ? '#1e293b' : '#5f6570')
    }
    // Apply initial selection
    updateSelectionHighlight()

    // ---- Hover handlers ----
    node.on('mouseenter', function (e, d) {
      const neighbors = adjacency.get(d.id) || new Set()
      const connected = connectedEdges.get(d.id) || new Set()

      node.selectAll('circle').transition().duration(150)
        .attr('opacity', n => n.id === d.id || neighbors.has(n.id) ? 1 : 0.12)
      node.selectAll('text').transition().duration(150)
        .attr('opacity', n => n.id === d.id || neighbors.has(n.id) ? 1 : 0.12)
      link.transition().duration(150)
        .attr('opacity', (_, i) => connected.has(i) ? 1 : 0.12)
        .attr('stroke-width', (_, i) => connected.has(i) ? 2.5 : 1.5)

      d3.select(this).select('circle').transition().duration(150).attr('r', 12)

      setTooltip({
        x: e.clientX, y: e.clientY,
        name: d.name, type: nodeTypeLabel(d.node_type),
      })
    })

    node.on('mouseleave', function () {
      node.selectAll('circle').transition().duration(200).attr('opacity', 1)
      node.selectAll('text').transition().duration(200).attr('opacity', 1)
      link.transition().duration(200).attr('opacity', 1).attr('stroke-width', 1.5)
      d3.select(this).select('circle').transition().duration(200).attr('r', 8)
      setTooltip(null)
      // Restore selection highlight
      updateSelectionHighlight()
    })

    // ---- Click handler ----
    node.on('click', (e, d) => {
      e.stopPropagation()
      const isDeselect = d.id === selectedNodeIdRef.current
      setSelectedNodeId(isDeselect ? null : d.id)
      onNodeClick?.(d)

      // Smoothly center viewport on the clicked node
      if (!isDeselect && d.x !== undefined && d.y !== undefined) {
        const currentTransform = d3.zoomTransform(svg.node())
        const targetX = W / 2 - d.x * currentTransform.k
        const targetY = H / 2 - d.y * currentTransform.k
        svg.transition().duration(400).call(
          zoom.transform,
          d3.zoomIdentity.translate(targetX, targetY).scale(currentTransform.k)
        )
      }
    })

    // Click on background deselects
    svg.on('click', () => {
      setSelectedNodeId(null)
      updateSelectionHighlight()
    })

    // ---- Edge labels ----
    let edgeLabelsDrawn = false
    const drawEdgeLabels = () => {
      if (edgeLabelsDrawn || simEdges.length === 0) return
      edgeLabelsDrawn = true

      const edgeLabelG = g.append('g').attr('class', 'edge-labels')

      edgeLabelG.selectAll('path').data(simEdges).join('path')
        .attr('id', (_, i) => `edge-path-${renderId}-${i}`)
        .attr('d', e => {
          const sx = e.source.x, sy = e.source.y
          const tx = e.target.x, ty = e.target.y
          return `M${sx},${sy}L${tx},${ty}`
        })
        .attr('fill', 'none').attr('stroke', 'none')

      // Edge text labels disabled — legend already indicates line meaning
      edgeLabelG.selectAll('text').data(simEdges).join('text')
        .attr('dy', -3).attr('font-size', 8).attr('fill', '#9ca3af')
        .attr('text-anchor', 'middle')
        .append('textPath')
        .attr('href', (_, i) => `#edge-path-${renderId}-${i}`)
        .attr('startOffset', '50%')
        .text('')
    }

    // ---- Tick ----
    sim.on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })

    // ---- End ----
    sim.on('end', () => {
      if (!initialTransform.current && simNodes.length > 0) {
        const xs = simNodes.map(n => n.x), ys = simNodes.map(n => n.y)
        const xMin = Math.min(...xs), xMax = Math.max(...xs)
        const yMin = Math.min(...ys), yMax = Math.max(...ys)
        const bboxW = Math.max(xMax - xMin, 1), bboxH = Math.max(yMax - yMin, 1)
        const scale = Math.min(W / (bboxW + 80), H / (bboxH + 80), 2)
        const tx = W / 2 - (xMin + xMax) / 2 * scale
        const ty = H / 2 - (yMin + yMax) / 2 * scale
        initialTransform.current = d3.zoomIdentity.translate(tx, ty).scale(scale)
        svg.transition().duration(500).call(zoom.transform, initialTransform.current)
      }
      drawEdgeLabels()
    })

    // ---- Cleanup on re-render: stop old simulation to prevent CPU leak ----
    return () => { sim.stop() }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredNodes, filteredEdges, loading, hasData])

  // Sync selectedNodeId → D3 highlight when changed programmatically
  useEffect(() => {
    if (!hasData) return
    const svg = d3.select(svgRef.current)
    if (svg.empty()) return
    const node = svg.select('g').selectAll('g')
    if (node.empty()) return

    node.selectAll('circle')
      .attr('stroke', d => d.id === selectedNodeId ? '#f59e0b' : '#fff')
      .attr('stroke-width', d => d.id === selectedNodeId ? 3 : 2)
      .attr('filter', d => d.id === selectedNodeId ? `url(#${SELECTED_GLOW_ID})` : null)
    node.selectAll('text')
      .attr('font-weight', d => d.id === selectedNodeId ? '700' : '400')
      .attr('fill', d => d.id === selectedNodeId ? '#1e293b' : '#5f6570')
  }, [selectedNodeId, hasData])

  // ---- Render ----
  return (
    <div className="relative">
      {/* ---- Toolbar ---- */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        {/* Node type legend */}
        {Object.entries(COLORS).filter(([k]) => presentNodeTypes.includes(k) || k === 'default').map(([k, c]) => (
          <div key={k} className="flex items-center gap-1 text-2xs text-ink-muted">
            <div className="w-3 h-3 rounded-full" style={{ background: c }} />
            {nodeTypeLabel(k)}
          </div>
        ))}

        {/* Edge style legend */}
        {edges.length > 0 && (
          <>
            <div className="w-px h-4 bg-cloud-300 mx-1" />
            {Object.entries(LINE_STYLES).map(([rel, dash]) => (
              <div key={rel} className="flex items-center gap-1 text-2xs text-ink-muted">
                <svg width="16" height="8"><line x1="0" y1="4" x2="16" y2="4"
                  stroke="#9ca3af" strokeWidth="1.5" strokeDasharray={dash} /></svg>
                {RELATION_LABELS[rel]}
              </div>
            ))}
          </>
        )}

        <div className="flex-1" />

        {/* Search */}
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted" />
          <input
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            placeholder="搜索节点…"
            className="w-36 pl-7 pr-2 py-1.5 rounded-lg border border-cloud-300 text-xs
              bg-white focus:outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-50 transition-all"
          />
          {searchTerm && (
            <button onClick={() => setSearchTerm('')} aria-label="清除搜索"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink-body">
              <X size={12} aria-hidden="true" />
            </button>
          )}
        </div>

        {/* Type filter */}
        {presentNodeTypes.length > 1 && (
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            className="py-1.5 pl-2 pr-6 rounded-lg border border-cloud-300 text-xs
              bg-white focus:outline-none focus:border-sky-400 transition-all text-ink-body"
          >
            <option value="">全部类型</option>
            {presentNodeTypes.map(t => (
              <option key={t} value={t}>{nodeTypeLabel(t)}</option>
            ))}
          </select>
        )}

        {/* Node count */}
        <span className="text-2xs text-ink-muted">
          {filteredNodes.length}{nodes.length !== filteredNodes.length && `/${nodes.length}`} 节点
          {edges.length > 0 && ` · ${filteredEdges.length} 边`}
        </span>

        {/* Zoom controls */}
        <button onClick={handleZoomIn} className="p-1.5 rounded-lg hover:bg-cloud-100 text-ink-muted transition-colors" title="放大" aria-label="放大">
          <ZoomIn size={14} />
        </button>
        <button onClick={handleZoomOut} className="p-1.5 rounded-lg hover:bg-cloud-100 text-ink-muted transition-colors" title="缩小" aria-label="缩小">
          <ZoomOut size={14} />
        </button>
        <button onClick={handleReset} className="p-1.5 rounded-lg hover:bg-cloud-100 text-ink-muted transition-colors" title="重置视图" aria-label="重置视图">
          <RotateCcw size={14} />
        </button>
      </div>

      {/* ---- Graph container ---- */}
      <div ref={containerRef} className="w-full relative">
        {/* Loading state */}
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-cloud-200/80 rounded-xl border border-cloud-300">
            <div className="flex flex-col items-center gap-3">
              <Loader2 size={28} className="text-coral-400 animate-spin" />
              <p className="text-sm text-ink-muted">加载知识图谱…</p>
            </div>
          </div>
        )}

        {/* Error state */}
        {!loading && error && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-cloud-200/80 rounded-xl border border-cloud-300">
            <div className="flex flex-col items-center gap-3 max-w-xs text-center">
              <AlertCircle size={28} className="text-rose-400" />
              <p className="text-sm text-ink-body font-medium">加载失败</p>
              <p className="text-xs text-ink-muted">{error}</p>
              {onRetry && (
                <button onClick={onRetry}
                  className="px-4 py-2 text-xs font-medium text-white bg-sky-500 rounded-lg hover:bg-sky-600 transition-colors">
                  重试
                </button>
              )}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && !hasData && (
          <div className="flex items-center justify-center rounded-xl border border-cloud-300 bg-cloud-200"
            style={{ minHeight: 350, height: 450 }}>
            <div className="flex flex-col items-center gap-3 text-center">
              <Database size={32} className="text-cloud-300" />
              <p className="text-sm text-ink-body font-medium">暂无知识图谱数据</p>
              <p className="text-xs text-ink-muted max-w-xs">
                导入文档后，系统将自动抽取实体与关系构建知识图谱
              </p>
            </div>
          </div>
        )}

        {/* SVG graph */}
        {hasData && (
          <svg ref={svgRef}
            className="w-full rounded-xl border border-cloud-300 bg-cloud-200"
            style={{ minHeight: 350, height: 450 }}
            role="img" aria-label="知识图谱可视化"
            tabIndex={0}
          />
        )}
      </div>

      {/* ---- Tooltip ---- */}
      {tooltip && (
        <div className="fixed z-50 pointer-events-none px-2.5 py-1.5 rounded-lg bg-ink-primary text-white text-xs shadow-lg max-w-56"
          style={{ left: tooltip.x + 14, top: tooltip.y - 10 }}>
          <p className="font-medium truncate">{tooltip.name}</p>
          <p className="text-cloud-300 text-2xs">{tooltip.type}</p>
        </div>
      )}

      {/* ---- Node count notice (when truncated) ---- */}
      {hasData && summary && summary.total_nodes > nodes.length && (
        <p className="mt-2 text-2xs text-ink-muted text-center">
          显示最近 {nodes.length} 个节点（共 {summary.total_nodes} 个）
        </p>
      )}
    </div>
  )
}
