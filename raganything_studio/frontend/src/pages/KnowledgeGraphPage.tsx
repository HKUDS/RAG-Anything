import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, RefreshCw, Settings, ZoomIn, ZoomOut } from 'lucide-react'
import { getGraphLabels, getGraphSubgraph } from '../api/client'
import type { GraphEdge, GraphNode } from '../types/studio'

interface SimNode extends GraphNode {
  x: number
  y: number
  vx: number
  vy: number
}

interface SimEdge extends GraphEdge {
  sourceNode?: SimNode
  targetNode?: SimNode
}

const NODE_RADIUS = 18
const LINK_DISTANCE = 120
const CHARGE = -320
const ALPHA_DECAY = 0.015
const VELOCITY_DECAY = 0.45

function useForceSimulation(nodes: GraphNode[], edges: GraphEdge[]) {
  const [simNodes, setSimNodes] = useState<SimNode[]>([])
  const [simEdges, setSimEdges] = useState<SimEdge[]>([])
  const frameRef = useRef<number | null>(null)
  const alphaRef = useRef(1)
  const nodesRef = useRef<SimNode[]>([])

  useEffect(() => {
    if (nodes.length === 0) {
      setSimNodes([])
      setSimEdges([])
      return
    }

    const angleStep = (2 * Math.PI) / nodes.length
    const initialNodes: SimNode[] = nodes.map((n, i) => ({
      ...n,
      x: 400 + Math.cos(angleStep * i) * 180,
      y: 300 + Math.sin(angleStep * i) * 180,
      vx: 0,
      vy: 0,
    }))
    nodesRef.current = initialNodes
    alphaRef.current = 1

    const nodeById = new Map(initialNodes.map((n) => [n.id, n]))
    const linkedEdges: SimEdge[] = edges.map((e) => ({
      ...e,
      sourceNode: nodeById.get(e.source),
      targetNode: nodeById.get(e.target),
    }))
    setSimEdges(linkedEdges)

    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)

    function tick() {
      const ns = nodesRef.current
      if (alphaRef.current < 0.005) {
        setSimNodes([...ns])
        return
      }

      const alpha = alphaRef.current

      for (let i = 0; i < ns.length; i++) {
        for (let j = i + 1; j < ns.length; j++) {
          const dx = ns[j].x - ns[i].x || 0.1
          const dy = ns[j].y - ns[i].y || 0.1
          const dist2 = dx * dx + dy * dy
          const dist = Math.sqrt(dist2 + 1)
          const force = (CHARGE * alpha) / Math.max(dist2, 1)
          ns[i].vx -= (dx * force) / dist
          ns[i].vy -= (dy * force) / dist
          ns[j].vx += (dx * force) / dist
          ns[j].vy += (dy * force) / dist
        }
      }

      for (const e of linkedEdges) {
        const src = e.sourceNode
        const tgt = e.targetNode
        if (!src || !tgt) continue
        const dx = tgt.x - src.x
        const dy = tgt.y - src.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const force = ((dist - LINK_DISTANCE) * alpha * 0.3) / dist
        src.vx += dx * force
        src.vy += dy * force
        tgt.vx -= dx * force
        tgt.vy -= dy * force
      }

      const cx = ns.reduce((s, n) => s + n.x, 0) / ns.length
      const cy = ns.reduce((s, n) => s + n.y, 0) / ns.length
      for (const n of ns) {
        n.vx += (400 - cx) * alpha * 0.05
        n.vy += (300 - cy) * alpha * 0.05
        n.vx *= VELOCITY_DECAY
        n.vy *= VELOCITY_DECAY
        n.x += n.vx
        n.y += n.vy
      }

      alphaRef.current *= 1 - ALPHA_DECAY
      setSimNodes([...ns])
      frameRef.current = requestAnimationFrame(tick)
    }

    setSimNodes([...initialNodes])
    frameRef.current = requestAnimationFrame(tick)

    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    }
  }, [nodes, edges])

  return { simNodes, simEdges }
}

const LABEL_COLORS = [
  '#6366f1', '#0ea5e9', '#10b981', '#f59e0b',
  '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6',
]

function labelColor(label: string): string {
  let hash = 0
  for (let i = 0; i < label.length; i++) hash = (hash * 31 + label.charCodeAt(i)) & 0xffffffff
  return LABEL_COLORS[Math.abs(hash) % LABEL_COLORS.length]
}

export default function KnowledgeGraphPage() {
  const [selectedLabel, setSelectedLabel] = useState<string>('')
  const [maxDepth, setMaxDepth] = useState(3)
  const [maxNodes, setMaxNodes] = useState(200)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [hoveredNode, setHoveredNode] = useState<SimNode | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const svgRef = useRef<SVGSVGElement>(null)
  const panRef = useRef(pan)
  panRef.current = pan

  const { data: labelsData, isLoading: labelsLoading, error: labelsError, refetch: refetchLabels } = useQuery({
    queryKey: ['graph-labels'],
    queryFn: () => getGraphLabels(),
    staleTime: 30_000,
  })

  useEffect(() => {
    if (labelsData?.labels?.length && !selectedLabel) {
      setSelectedLabel(labelsData.labels[0])
    }
  }, [labelsData, selectedLabel])

  const { data: graphData, isLoading: graphLoading, error: graphError, refetch: refetchGraph } = useQuery({
    queryKey: ['graph-subgraph', selectedLabel, maxDepth, maxNodes],
    queryFn: () => getGraphSubgraph(selectedLabel, maxDepth, maxNodes),
    enabled: !!selectedLabel,
    staleTime: 30_000,
  })

  const nodes: GraphNode[] = graphData?.nodes ?? []
  const edges: GraphEdge[] = graphData?.edges ?? []
  const { simNodes, simEdges } = useForceSimulation(nodes, edges)
  const nodeMap = new Map(simNodes.map((n) => [n.id, n]))

  function handleWheel(e: React.WheelEvent) {
    e.preventDefault()
    setZoom((z) => Math.max(0.2, Math.min(4, z * (e.deltaY < 0 ? 1.1 : 0.9))))
  }

  const handleSvgMouseDown = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if ((e.target as Element) !== svgRef.current && !(e.target as Element).classList.contains('graph-canvas-bg')) return
    const startX = e.clientX - panRef.current.x
    const startY = e.clientY - panRef.current.y
    function onMove(mv: MouseEvent) {
      setPan({ x: mv.clientX - startX, y: mv.clientY - startY })
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [])

  function handleNodeMouseDown(e: React.MouseEvent, nodeId: string) {
    e.stopPropagation()
    const node = nodeMap.get(nodeId)
    if (!node || !svgRef.current) return
    const rect = svgRef.current.getBoundingClientRect()
    const ox = (e.clientX - rect.left - panRef.current.x) / zoom - node.x
    const oy = (e.clientY - rect.top - panRef.current.y) / zoom - node.y
    function onMove(mv: MouseEvent) {
      const n = nodeMap.get(nodeId)
      if (!n) return
      n.x = (mv.clientX - rect.left - panRef.current.x) / zoom - ox
      n.y = (mv.clientY - rect.top - panRef.current.y) / zoom - oy
      n.vx = 0
      n.vy = 0
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  const isLoading = labelsLoading || graphLoading
  const error = labelsError || graphError

  return (
    <section className="graph-workspace">
      <div className="graph-toolbar">
        <button
          className="icon-button graph-refresh"
          type="button"
          title="Reload graph"
          onClick={() => { refetchLabels(); refetchGraph() }}
        >
          <RefreshCw size={16} className={isLoading ? 'spin' : ''} />
        </button>

        <select
          className="graph-select"
          value={selectedLabel}
          onChange={(e) => setSelectedLabel(e.target.value)}
          disabled={!labelsData?.labels?.length}
        >
          {!labelsData?.labels?.length
            ? <option value="">No nodes yet</option>
            : labelsData.labels.map((l) => <option key={l} value={l}>{l}</option>)
          }
        </select>

        <span className="graph-stat">
          {nodes.length} nodes · {edges.length} edges
          {graphData?.is_truncated && <span className="graph-truncated"> (truncated)</span>}
        </span>
      </div>

      {error && (
        <div className="graph-error-banner">
          <AlertTriangle size={16} />
          {String((error as Error).message)}
        </div>
      )}

      {!isLoading && !error && nodes.length === 0 && (
        <div className="graph-empty">
          <span className="graph-empty-dot" />
          {labelsData?.labels?.length
            ? 'No nodes found for this label'
            : 'No knowledge graph yet — process a document first'}
        </div>
      )}

      {nodes.length > 0 && (
        <svg
          ref={svgRef}
          className="graph-canvas"
          onWheel={handleWheel}
          onMouseDown={handleSvgMouseDown}
        >
          <rect className="graph-canvas-bg" width="100%" height="100%" fill="transparent" />
          <defs>
            <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="#64748b" opacity="0.6" />
            </marker>
          </defs>
          <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
            {simEdges.map((e) => {
              const src = nodeMap.get(e.source)
              const tgt = nodeMap.get(e.target)
              if (!src || !tgt) return null
              const dx = tgt.x - src.x
              const dy = tgt.y - src.y
              const dist = Math.sqrt(dx * dx + dy * dy) || 1
              const x2 = tgt.x - (dx / dist) * (NODE_RADIUS + 4)
              const y2 = tgt.y - (dy / dist) * (NODE_RADIUS + 4)
              return (
                <g key={e.id}>
                  <line
                    x1={src.x} y1={src.y} x2={x2} y2={y2}
                    stroke="#64748b" strokeOpacity={0.5} strokeWidth={1.5}
                    markerEnd="url(#arrowhead)"
                  />
                  {e.type && (
                    <text
                      x={(src.x + tgt.x) / 2}
                      y={(src.y + tgt.y) / 2 - 5}
                      textAnchor="middle"
                      fontSize={10}
                      fill="#94a3b8"
                      style={{ pointerEvents: 'none', userSelect: 'none' }}
                    >
                      {e.type}
                    </text>
                  )}
                </g>
              )
            })}

            {simNodes.map((n) => {
              const color = labelColor(n.labels[0] ?? n.id)
              return (
                <g
                  key={n.id}
                  transform={`translate(${n.x},${n.y})`}
                  style={{ cursor: 'pointer' }}
                  onMouseDown={(e) => handleNodeMouseDown(e, n.id)}
                  onMouseEnter={() => setHoveredNode(n)}
                  onMouseLeave={() => setHoveredNode(null)}
                >
                  <circle r={NODE_RADIUS} fill={color} fillOpacity={0.85} stroke="#fff" strokeWidth={1.5} />
                  <text
                    textAnchor="middle" dy="0.35em" fontSize={11} fill="#fff" fontWeight={600}
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {n.id.length > 10 ? n.id.slice(0, 9) + '…' : n.id}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>
      )}

      {hoveredNode && (
        <div className="graph-tooltip">
          <div className="graph-tooltip__id">{hoveredNode.id}</div>
          {hoveredNode.labels.length > 0 && (
            <div className="graph-tooltip__labels">{hoveredNode.labels.join(', ')}</div>
          )}
          {Object.entries(hoveredNode.properties).slice(0, 4).map(([k, v]) => (
            <div key={k} className="graph-tooltip__prop">
              <span className="graph-tooltip__key">{k}</span>
              <span className="graph-tooltip__val">{String(v).slice(0, 60)}</span>
            </div>
          ))}
        </div>
      )}

      <div className="graph-side-tools">
        <button className="icon-button" title="Zoom in" onClick={() => setZoom((z) => Math.min(4, z * 1.2))}>
          <ZoomIn size={15} />
        </button>
        <button className="icon-button" title="Zoom out" onClick={() => setZoom((z) => Math.max(0.2, z / 1.2))}>
          <ZoomOut size={15} />
        </button>
        <button className="icon-button" title="Reset view" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }) }}>
          <RefreshCw size={15} />
        </button>
        <button
          className={`icon-button${showSettings ? ' active' : ''}`}
          title="Graph settings"
          onClick={() => setShowSettings((s) => !s)}
        >
          <Settings size={15} />
        </button>
      </div>

      {showSettings && (
        <div className="graph-settings-panel">
          <label>
            Max depth
            <input type="number" min={1} max={6} value={maxDepth}
              onChange={(e) => setMaxDepth(Number(e.target.value))} />
          </label>
          <label>
            Max nodes
            <input type="number" min={10} max={1000} step={10} value={maxNodes}
              onChange={(e) => setMaxNodes(Number(e.target.value))} />
          </label>
        </div>
      )}

      <div className="graph-footer-note">
        D: {maxDepth}&nbsp;&nbsp;Max: {maxNodes}
        {zoom !== 1 && <>&nbsp;&nbsp;Zoom: {zoom.toFixed(1)}x</>}
      </div>
    </section>
  )
}
