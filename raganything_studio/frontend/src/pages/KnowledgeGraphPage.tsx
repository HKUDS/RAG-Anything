import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { SigmaContainer, useRegisterEvents, useSetSettings, useSigma } from '@react-sigma/core'
import { useLayoutForceAtlas2 } from '@react-sigma/layout-forceatlas2'
import { useLayoutCircular } from '@react-sigma/layout-circular'
import { useLayoutRandom } from '@react-sigma/layout-random'
import { NodeBorderProgram } from '@sigma/node-border'
import { EdgeArrowProgram, NodeCircleProgram, NodePointProgram } from 'sigma/rendering'
import { createEdgeCurveProgram, EdgeCurvedArrowProgram } from '@sigma/edge-curve'
import { DirectedGraph } from 'graphology'
import type { Settings as SigmaSettings } from 'sigma/settings'
import {
  AlertTriangle,
  Boxes,
  Eye,
  EyeOff,
  Filter,
  GitBranch,
  Layers,
  LocateFixed,
  Maximize2,
  RefreshCw,
  Search,
  Settings as SettingsIcon,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import { getGraphLabels, getGraphSubgraph } from '../api/client'
import type { GraphEdge, GraphNode, KnowledgeGraphResponse } from '../types/studio'

import '@react-sigma/core/lib/style.css'

// ── Node types & colors (aligned with LightRAG palette) ──────────
type NodeType = 'document' | 'page' | 'section' | 'text' | 'image' | 'table' | 'equation' | 'entity'

const NODE_COLORS: Record<NodeType, string> = {
  document: '#4169E1',
  page: '#00bfa0',
  section: '#00cc00',
  text: '#5D6D7E',
  image: '#f59e0b',
  table: '#8b5cf6',
  equation: '#ec4899',
  entity: '#e3493b',
}
const NODE_TYPES: NodeType[] = ['document', 'page', 'section', 'text', 'image', 'table', 'equation', 'entity']

const EDGE_COLOR_DEFAULT = '#888888'
const EDGE_COLOR_SELECTED = '#F57F17'
const NODE_COLOR_DISABLED = '#2a2a3a'
const NODE_BORDER_SELECTED = '#F57F17'

function emptyGraph(): KnowledgeGraphResponse {
  return { nodes: [], edges: [], is_truncated: false }
}

// ── Sigma settings factory ────────────────────────────────────────
function createSigmaSettings(): Partial<SigmaSettings> {
  return {
    allowInvalidContainer: true,
    defaultNodeType: 'default',
    defaultEdgeType: 'curvedNoArrow',
    renderEdgeLabels: false,
    edgeProgramClasses: {
      arrow: EdgeArrowProgram,
      curvedArrow: EdgeCurvedArrowProgram,
      curvedNoArrow: createEdgeCurveProgram(),
    } as any,
    nodeProgramClasses: {
      default: NodeBorderProgram,
      circle: NodeCircleProgram,
      point: NodePointProgram,
    } as any,
    labelGridCellSize: 60,
    labelRenderedSizeThreshold: 10,
    enableEdgeEvents: true,
    labelColor: { color: '#ffffff' },
    edgeLabelColor: { color: '#aaaaaa' },
    edgeLabelSize: 8,
    labelSize: 12,
  }
}

type Selection =
  | { kind: 'node'; id: string; node: GraphNode }
  | { kind: 'edge'; id: string; edge: GraphEdge }

// ── Inner controller (must live inside SigmaContainer) ────────────
interface GraphControllerProps {
  graph: KnowledgeGraphResponse
  maxNodes: number
  disabledNodeTypes: Set<string>
  disabledEdgeTypes: Set<string>
  searchText: string
  showEdgeLabels: boolean
  showNodeLabels: boolean
  selected: Selection | null
  onSelectNode: (id: string) => void
  onSelectEdge: (id: string) => void
  onClearSelection: () => void
  nodesByIdRef: React.MutableRefObject<Map<string, GraphNode>>
  edgesByIdRef: React.MutableRefObject<Map<string, GraphEdge>>
  nodeInfoRef: React.MutableRefObject<Map<string, { type: NodeType; degree: number }>>
  edgeTypeRef: React.MutableRefObject<Map<string, string>>
  layoutTrigger: { name: 'forceatlas2' | 'circular' | 'random'; seq: number }
}

const GraphController = ({
  graph,
  maxNodes,
  disabledNodeTypes,
  disabledEdgeTypes,
  searchText,
  showEdgeLabels,
  showNodeLabels,
  selected,
  onSelectNode,
  onSelectEdge,
  onClearSelection,
  nodesByIdRef,
  edgesByIdRef,
  nodeInfoRef,
  edgeTypeRef,
  layoutTrigger,
}: GraphControllerProps) => {
  const sigma = useSigma()
  const registerEvents = useRegisterEvents()
  const setSettings = useSetSettings()
  const { assign: assignForceAtlas } = useLayoutForceAtlas2({ iterations: 100 })
  const { assign: assignCircular } = useLayoutCircular()
  const { assign: assignRandom } = useLayoutRandom()

  const [focusedNode, setFocusedNode] = useState<string | null>(null)
  const [focusedEdge, setFocusedEdge] = useState<string | null>(null)

  // Rebuild graphology graph whenever data/filters change
  useEffect(() => {
    const g = new DirectedGraph()
    const nodeInfo = buildNodeInfo(graph.nodes, graph.edges)
    nodeInfoRef.current = nodeInfo

    const term = searchText.trim().toLowerCase()
    const searchHits = new Set<string>()
    if (term) {
      for (const node of graph.nodes) {
        if (JSON.stringify(node).toLowerCase().includes(term)) searchHits.add(node.id)
      }
    }

    const filteredNodes = graph.nodes
      .filter((n) => {
        const t = nodeInfo.get(n.id)?.type ?? 'entity'
        return !disabledNodeTypes.has(t)
      })
      .sort((a, b) => (nodeInfo.get(b.id)?.degree ?? 0) - (nodeInfo.get(a.id)?.degree ?? 0))
      .slice(0, maxNodes)

    const visibleIds = new Set(filteredNodes.map((n) => n.id))

    for (const node of filteredNodes) {
      const info = nodeInfo.get(node.id) ?? { type: 'entity' as NodeType, degree: 0 }
      const color = NODE_COLORS[info.type]
      const size = Math.min(20, 4 + Math.sqrt(Math.max(info.degree, 1)) * 3)
      g.addNode(node.id, {
        label: compactLabel(node.id),
        color,
        borderColor: '#333355',
        size,
        x: Math.random(),
        y: Math.random(),
        nodeType: info.type,
        degree: info.degree,
        searchHit: searchHits.has(node.id),
      })
    }

    const seenEdges = new Set<string>()
    for (const edge of graph.edges) {
      const type = edgeTypeRef.current.get(edge.id) ?? normalizeEdgeType(edge)
      if (disabledEdgeTypes.has(type)) continue
      if (!visibleIds.has(edge.source) || !visibleIds.has(edge.target)) continue
      const key = `${edge.source}->${edge.target}`
      if (seenEdges.has(key)) continue
      seenEdges.add(key)
      try {
        g.addEdge(edge.source, edge.target, {
          label: type,
          color: EDGE_COLOR_DEFAULT,
          size: 1.5,
          type: 'curvedNoArrow',
        })
      } catch {
        // ignore duplicate edge errors from graphology
      }
    }

    sigma.setGraph(g as any)
    assignForceAtlas()
    sigma.refresh()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, disabledNodeTypes, disabledEdgeTypes, searchText, maxNodes])

  // Apply layout on demand
  useEffect(() => {
    if (layoutTrigger.seq === 0) return
    if (layoutTrigger.name === 'forceatlas2') assignForceAtlas()
    else if (layoutTrigger.name === 'circular') assignCircular()
    else assignRandom()
    sigma.refresh()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutTrigger])

  // Register mouse/click events
  useEffect(() => {
    registerEvents({
      clickNode: ({ node }) => {
        const nodeData = nodesByIdRef.current.get(node)
        if (nodeData) onSelectNode(node)
      },
      clickEdge: ({ edge }) => {
        const edgeData = edgesByIdRef.current.get(edge)
        if (edgeData) onSelectEdge(edge)
      },
      clickStage: () => onClearSelection(),
      enterNode: ({ node }) => setFocusedNode(node),
      leaveNode: () => setFocusedNode(null),
      enterEdge: ({ edge }) => setFocusedEdge(edge),
      leaveEdge: () => setFocusedEdge(null),
    })
  }, [registerEvents, onSelectNode, onSelectEdge, onClearSelection, nodesByIdRef, edgesByIdRef])

  // Reducers for visual state (hover, selection, fade)
  useEffect(() => {
    const selectedId = selected?.id ?? null
    const selectedKind = selected?.kind ?? null

    setSettings({
      renderEdgeLabels: showEdgeLabels,
      renderLabels: true,
      nodeReducer: (node, data) => {
        const g = sigma.getGraph()
        const newData = { ...data }

        const isSelected = node === selectedId && selectedKind === 'node'
        const isFocused = node === focusedNode
        const isNeighbour = selectedKind === 'node' && selectedId && g.hasNode(selectedId)
          ? g.neighbors(selectedId).includes(node)
          : false
        const isEdgeEndpoint = selectedKind === 'edge' && selectedId && g.hasEdge(selectedId)
          ? g.extremities(selectedId).includes(node)
          : false

        const isActive = isSelected || isFocused || isNeighbour || isEdgeEndpoint

        if (selectedId && !isActive) {
          newData.color = NODE_COLOR_DISABLED
          newData.borderColor = NODE_COLOR_DISABLED
        }

        if (isSelected) {
          newData.borderColor = NODE_BORDER_SELECTED
          newData.highlighted = true
        }

        if (!showNodeLabels && !isFocused && !isSelected && (data as any).degree < 3) {
          newData.label = ''
        }

        return newData
      },
      edgeReducer: (edge, data) => {
        const g = sigma.getGraph()
        const newData = { ...data, color: EDGE_COLOR_DEFAULT }

        const isSelectedEdge = edge === selectedId && selectedKind === 'edge'
        const isFocusedEdge = edge === focusedEdge
        const isConnectedToNode = selectedKind === 'node' && selectedId && g.hasNode(selectedId)
          ? g.hasEdge(edge) && g.extremities(edge).includes(selectedId)
          : false

        if (isSelectedEdge || isFocusedEdge || isConnectedToNode) {
          newData.color = EDGE_COLOR_SELECTED
        } else if (selectedId) {
          newData.color = '#1a1a2e'
        }

        return newData
      },
    })
  }, [sigma, selected, focusedNode, focusedEdge, showEdgeLabels, showNodeLabels, setSettings])

  return null
}

// ── Main page ─────────────────────────────────────────────────────
export default function KnowledgeGraphPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const nodesByIdRef = useRef<Map<string, GraphNode>>(new Map())
  const edgesByIdRef = useRef<Map<string, GraphEdge>>(new Map())
  const nodeInfoRef = useRef<Map<string, { type: NodeType; degree: number }>>(new Map())
  const edgeTypeRef = useRef<Map<string, string>>(new Map())

  const [graph, setGraph] = useState<KnowledgeGraphResponse>(emptyGraph)
  const [rootLabel, setRootLabel] = useState('')
  const [searchText, setSearchText] = useState('')
  const [showNodeLabels, setShowNodeLabels] = useState(true)
  const [showEdgeLabels, setShowEdgeLabels] = useState(false)
  const [maxNodes, setMaxNodes] = useState(150)
  const [maxDepth, setMaxDepth] = useState(2)
  const [disabledNodeTypes, setDisabledNodeTypes] = useState<Set<string>>(new Set())
  const [disabledEdgeTypes, setDisabledEdgeTypes] = useState<Set<string>>(new Set(['same_page_as']))
  const [selected, setSelected] = useState<Selection | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [showLegend, setShowLegend] = useState(true)
  const [showFilterBar, setShowFilterBar] = useState(false)
  const [layoutTrigger, setLayoutTrigger] = useState<{ name: 'forceatlas2' | 'circular' | 'random'; seq: number }>({
    name: 'forceatlas2',
    seq: 0,
  })

  const { data: labelsData, isLoading: labelsLoading, refetch: refetchLabels } = useQuery({
    queryKey: ['graph-labels'],
    queryFn: () => getGraphLabels(),
    staleTime: 30_000,
  })

  const { data: overviewData, isLoading: graphLoading, refetch: refetchOverview } = useQuery({
    queryKey: ['graph-overview', maxNodes],
    queryFn: () => getGraphSubgraph(null, 1, maxNodes),
    staleTime: 30_000,
  })

  const expandMutation = useMutation({
    mutationFn: (label: string) => getGraphSubgraph(label, 1, maxNodes),
    onSuccess: (next) => setGraph((cur) => mergeGraphs(cur, next, maxNodes)),
  })

  useEffect(() => {
    if (overviewData) {
      setGraph(overviewData)
      setSelected(null)
    }
  }, [overviewData])

  useEffect(() => {
    const labels = (labelsData as { labels?: string[] })?.labels
    if (labels?.length && !rootLabel) setRootLabel(labels[0])
  }, [labelsData, rootLabel])

  useEffect(() => {
    nodesByIdRef.current = new Map(graph.nodes.map((n) => [n.id, n]))
    edgesByIdRef.current = new Map(graph.edges.map((e) => [e.id, e]))
    edgeTypeRef.current = new Map(graph.edges.map((e) => [e.id, normalizeEdgeType(e)]))
  }, [graph])

  const sigmaSettings = useMemo(() => createSigmaSettings(), [])

  const availableNodeTypes = useMemo(() => {
    const found = new Set(graph.nodes.map((n) => inferNodeType(n)))
    return NODE_TYPES.filter((t) => found.has(t))
  }, [graph.nodes])

  const availableEdgeTypes = useMemo(() => {
    return [...new Set(graph.edges.map(normalizeEdgeType))].sort()
  }, [graph.edges])

  const expandedRef = useRef(new Set<string>())

  const onSelectNode = useCallback((id: string) => {
    const node = nodesByIdRef.current.get(id)
    if (!node) return
    setSelected({ kind: 'node', id, node })
    if (!expandedRef.current.has(id)) {
      expandedRef.current.add(id)
      expandMutation.mutate(id)
    }
  }, [expandMutation])

  const onSelectEdge = useCallback((id: string) => {
    const edge = edgesByIdRef.current.get(id)
    if (!edge) return
    setSelected({ kind: 'edge', id, edge })
  }, [])

  const onClearSelection = useCallback(() => setSelected(null), [])

  function reloadGraph() {
    setSelected(null)
    expandedRef.current = new Set()
    refetchLabels()
    refetchOverview()
  }

  function loadRootLabel() {
    if (!rootLabel) return
    setSelected(null)
    expandedRef.current = new Set([rootLabel])
    getGraphSubgraph(rootLabel, maxDepth, maxNodes).then(setGraph)
  }

  function triggerLayout(name: 'forceatlas2' | 'circular' | 'random') {
    setLayoutTrigger((prev) => ({ name, seq: prev.seq + 1 }))
  }

  const isLoading = labelsLoading || graphLoading || expandMutation.isPending
  const selectedNode = selected?.kind === 'node' ? selected.node : null
  const selectedEdge = selected?.kind === 'edge' ? selected.edge : null

  return (
    <div ref={containerRef} className="graph-workspace">
      <SigmaContainer
        settings={sigmaSettings}
        className="graph-sigma-container"
      >
        <GraphController
          graph={graph}
          maxNodes={maxNodes}
          disabledNodeTypes={disabledNodeTypes}
          disabledEdgeTypes={disabledEdgeTypes}
          searchText={searchText}
          showEdgeLabels={showEdgeLabels}
          showNodeLabels={showNodeLabels}
          selected={selected}
          onSelectNode={onSelectNode}
          onSelectEdge={onSelectEdge}
          onClearSelection={onClearSelection}
          nodesByIdRef={nodesByIdRef}
          edgesByIdRef={edgesByIdRef}
          nodeInfoRef={nodeInfoRef}
          edgeTypeRef={edgeTypeRef}
          layoutTrigger={layoutTrigger}
        />

        {/* ── Top-left: label selector + search ── */}
        <div className="graph-top-left">
          <div className="graph-glass-cluster">
            <button className="graph-icon-btn" type="button" title="Reload graph" onClick={reloadGraph}>
              <RefreshCw size={15} className={isLoading ? 'spin' : ''} />
            </button>
            <select
              className="graph-glass-select"
              value={rootLabel}
              onChange={(e) => setRootLabel(e.target.value)}
            >
              {!((labelsData as { labels?: string[] })?.labels?.length)
                ? <option value="">No graph labels</option>
                : (labelsData as { labels: string[] }).labels.map((l: string) => <option key={l} value={l}>{l}</option>)}
            </select>
            <button
              className="graph-focus-btn"
              type="button"
              onClick={loadRootLabel}
              disabled={!rootLabel}
            >
              <LocateFixed size={14} />
              Focus
            </button>
          </div>

          <label className="graph-glass-cluster graph-search-wrap">
            <Search size={14} />
            <input
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Search graph…"
              className="graph-search-input"
            />
          </label>
        </div>

        {/* ── Bottom-left: vertical toolbar (LightRAG style) ── */}
        <div className="graph-bottom-toolbar">
          <button className="graph-icon-btn" title="ForceAtlas2 layout" onClick={() => triggerLayout('forceatlas2')}>
            <Boxes size={16} />
          </button>
          <button className="graph-icon-btn" title="Circular layout" onClick={() => triggerLayout('circular')}>
            <Layers size={16} />
          </button>
          <button className="graph-icon-btn" title="Random layout" onClick={() => triggerLayout('random')}>
            <AlertTriangle size={15} />
          </button>
          <div className="graph-toolbar-sep" />
          <button className="graph-icon-btn" title="Zoom in">
            <ZoomIn size={15} />
          </button>
          <button className="graph-icon-btn" title="Zoom out">
            <ZoomOut size={15} />
          </button>
          <button className="graph-icon-btn" title="Fit graph">
            <Maximize2 size={15} />
          </button>
          <div className="graph-toolbar-sep" />
          <button
            className={`graph-icon-btn${showNodeLabels ? ' active' : ''}`}
            title="Toggle node labels"
            onClick={() => setShowNodeLabels((v) => !v)}
          >
            {showNodeLabels ? <Eye size={15} /> : <EyeOff size={15} />}
          </button>
          <button
            className={`graph-icon-btn${showEdgeLabels ? ' active' : ''}`}
            title="Toggle edge labels"
            onClick={() => setShowEdgeLabels((v) => !v)}
          >
            <GitBranch size={15} />
          </button>
          <button
            className={`graph-icon-btn${showFilterBar ? ' active' : ''}`}
            title="Filters"
            onClick={() => setShowFilterBar((v) => !v)}
          >
            <Filter size={15} />
          </button>
          <button
            className={`graph-icon-btn${showSettings ? ' active' : ''}`}
            title="Settings"
            onClick={() => setShowSettings((v) => !v)}
          >
            <SettingsIcon size={15} />
          </button>
        </div>

        {/* ── Settings popover ── */}
        {showSettings && (
          <div className="graph-settings-panel">
            <div className="graph-settings-title">Settings</div>
            <label className="graph-settings-row">
              <span>Max nodes</span>
              <input
                type="number" min={20} max={1000} step={10}
                value={maxNodes}
                onChange={(e) => setMaxNodes(Number(e.target.value))}
              />
            </label>
            <label className="graph-settings-row">
              <span>Focus depth</span>
              <input
                type="number" min={1} max={6}
                value={maxDepth}
                onChange={(e) => setMaxDepth(Number(e.target.value))}
              />
            </label>
          </div>
        )}

        {/* ── Filter bar ── */}
        {showFilterBar && (
          <div className="graph-filter-overlay">
            <div className="graph-filter-group">
              {availableNodeTypes.map((type) => (
                <button
                  key={type}
                  className={`graph-chip${disabledNodeTypes.has(type) ? '' : ' active'}`}
                  onClick={() => toggleSet(type, setDisabledNodeTypes)}
                >
                  <span className="graph-chip-dot" style={{ background: NODE_COLORS[type] }} />
                  {type}
                </button>
              ))}
            </div>
            {availableEdgeTypes.length > 0 && (
              <div className="graph-filter-group graph-filter-group--edges">
                {availableEdgeTypes.map((type) => (
                  <button
                    key={type}
                    className={`graph-chip graph-chip--edge${disabledEdgeTypes.has(type) ? '' : ' active'}`}
                    onClick={() => toggleSet(type, setDisabledEdgeTypes)}
                  >
                    {type}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Top-right: properties panel (LightRAG PropertiesView style) ── */}
        {selected && (
          <div className="graph-props-panel">
            {selectedNode
              ? <NodeProperties
                  node={selectedNode}
                  info={nodeInfoRef.current.get(selectedNode.id)}
                  onClose={onClearSelection}
                />
              : selectedEdge
                ? <EdgeProperties
                    edge={selectedEdge}
                    edgeType={edgeTypeRef.current.get(selectedEdge.id) ?? normalizeEdgeType(selectedEdge)}
                    onClose={onClearSelection}
                  />
                : null}
          </div>
        )}

        {/* ── Bottom-right: legend ── */}
        {showLegend && (
          <div className="graph-legend-panel">
            <div className="graph-legend-header">
              <span>Legend</span>
              <button className="graph-legend-close" onClick={() => setShowLegend(false)}>×</button>
            </div>
            {NODE_TYPES.map((type) => (
              <div key={type} className="graph-legend-item">
                <span className="graph-legend-dot" style={{ background: NODE_COLORS[type] }} />
                <span>{type}</span>
              </div>
            ))}
          </div>
        )}
        {!showLegend && (
          <button className="graph-legend-btn" onClick={() => setShowLegend(true)} title="Show legend">
            <Layers size={14} />
          </button>
        )}

        {/* ── Stats pill ── */}
        <div className="graph-stats-pill">
          {graph.nodes.length} nodes · {graph.edges.length} edges
          {graph.is_truncated && <span className="graph-truncated-tag">truncated</span>}
        </div>

        {/* ── Loading overlay ── */}
        {isLoading && (
          <div className="graph-loading-overlay">
            <div className="graph-spinner" />
            <p>Loading graph…</p>
          </div>
        )}

        {/* ── Empty state ── */}
        {!isLoading && graph.nodes.length === 0 && (
          <div className="graph-empty-overlay">
            <div className="graph-empty-icon" />
            <p>No knowledge graph yet — process a document first</p>
          </div>
        )}
      </SigmaContainer>
    </div>
  )
}

// ── Properties panels ─────────────────────────────────────────────
function NodeProperties({
  node,
  info,
  onClose,
}: {
  node: GraphNode
  info: { type: NodeType; degree: number } | undefined
  onClose: () => void
}) {
  const nodeType = info?.type ?? 'entity'
  const color = NODE_COLORS[nodeType]
  const entries = Object.entries(node.properties)
    .filter(([k]) => k !== 'created_at' && k !== 'truncate')
    .slice(0, 20)

  const isImageNode = nodeType === 'image'
  const sourceId = node.properties.source_id as string | undefined
  const mediaUrl = isImageNode
    ? `/api/graph/node-media/${encodeURIComponent(node.id)}${sourceId ? `?source_id=${encodeURIComponent(sourceId)}` : ''}`
    : null

  return (
    <div className="graph-props-card">
      <div className="graph-props-header">
        <h3 className="graph-props-title graph-props-title--node">Node Properties</h3>
        <button className="graph-props-close" onClick={onClose}>×</button>
      </div>

      <div className="graph-props-meta-grid">
        <div className="graph-props-meta-cell">
          <small>Type</small>
          <strong style={{ color }}>{nodeType}</strong>
        </div>
        <div className="graph-props-meta-cell">
          <small>Degree</small>
          <strong>{info?.degree ?? '—'}</strong>
        </div>
      </div>

      <div className="graph-props-scrollbody">
        {mediaUrl && (
          <div className="graph-props-kv-section">
            <div className="graph-props-section-label">Preview</div>
            <div className="graph-props-image-wrap">
              <img
                src={mediaUrl}
                alt={node.id}
                className="graph-props-image"
                onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
              />
            </div>
          </div>
        )}

        <div className="graph-props-kv-section">
          <div className="graph-props-section-label">ID</div>
          <div className="graph-props-kv-list">
            <div className="graph-props-kv-row">
              <span className="graph-props-kv-val graph-props-mono">{node.id}</span>
            </div>
          </div>
        </div>

        {node.labels.length > 0 && (
          <div className="graph-props-kv-section">
            <div className="graph-props-section-label">Labels</div>
            <div className="graph-props-kv-list">
              <div className="graph-props-kv-row">
                <span className="graph-props-kv-val">{node.labels.join(', ')}</span>
              </div>
            </div>
          </div>
        )}

        {entries.length > 0 && (
          <div className="graph-props-kv-section">
            <div className="graph-props-section-label graph-props-amber">Properties</div>
            <div className="graph-props-kv-list">
              {entries.map(([k, v]) => (
                <div key={k} className="graph-props-kv-row">
                  <span className="graph-props-kv-key">{k}</span>
                  <span className="graph-props-kv-val">{formatValue(v)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function EdgeProperties({
  edge,
  edgeType,
  onClose,
}: {
  edge: GraphEdge
  edgeType: string
  onClose: () => void
}) {
  const entries = Object.entries(edge.properties)
    .filter(([k]) => k !== 'created_at' && k !== 'truncate')
    .slice(0, 20)

  return (
    <div className="graph-props-card">
      <div className="graph-props-header">
        <h3 className="graph-props-title graph-props-title--edge">Edge Properties</h3>
        <button className="graph-props-close" onClick={onClose}>×</button>
      </div>

      <div className="graph-props-scrollbody">
        <div className="graph-props-kv-section">
          <div className="graph-props-section-label">Relation</div>
          <div className="graph-props-kv-list">
            <div className="graph-props-kv-row">
              <span className="graph-props-kv-val">{edgeType}</span>
            </div>
          </div>
        </div>

        <div className="graph-props-kv-section">
          <div className="graph-props-section-label">Source → Target</div>
          <div className="graph-props-kv-list">
            <div className="graph-props-kv-row">
              <span className="graph-props-kv-key">from</span>
              <span className="graph-props-kv-val graph-props-mono">{compactLabel(edge.source)}</span>
            </div>
            <div className="graph-props-kv-row">
              <span className="graph-props-kv-key">to</span>
              <span className="graph-props-kv-val graph-props-mono">{compactLabel(edge.target)}</span>
            </div>
          </div>
        </div>

        {entries.length > 0 && (
          <div className="graph-props-kv-section">
            <div className="graph-props-section-label graph-props-amber">Properties</div>
            <div className="graph-props-kv-list">
              {entries.map(([k, v]) => (
                <div key={k} className="graph-props-kv-row">
                  <span className="graph-props-kv-key">{k}</span>
                  <span className="graph-props-kv-val">{formatValue(v)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Pure utilities ────────────────────────────────────────────────
function buildNodeInfo(nodes: GraphNode[], edges: GraphEdge[]) {
  const degree = new Map<string, number>()
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
  }
  return new Map(nodes.map((n) => [n.id, { type: inferNodeType(n), degree: degree.get(n.id) ?? 0 }]))
}

function inferNodeType(node: GraphNode): NodeType {
  const h = [node.id, ...node.labels, String(node.properties.type ?? ''), String(node.properties.node_type ?? '')].join(' ').toLowerCase()
  if (/\bdocument|doc\b/.test(h)) return 'document'
  if (/\bpage\b/.test(h)) return 'page'
  if (/\bsection|heading\b/.test(h)) return 'section'
  if (/\bimage|figure|picture\b/.test(h)) return 'image'
  if (/\btable|tabular\b/.test(h)) return 'table'
  if (/\bequation|formula|math\b/.test(h)) return 'equation'
  if (/\btext|chunk|paragraph|content\b/.test(h)) return 'text'
  return 'entity'
}

function normalizeEdgeType(edge: GraphEdge): string {
  return String(edge.type ?? edge.properties.type ?? edge.properties.relation_type ?? edge.properties.relationship ?? 'related_to')
}

function mergeGraphs(cur: KnowledgeGraphResponse, next: KnowledgeGraphResponse, max: number): KnowledgeGraphResponse {
  const nodes = new Map(cur.nodes.map((n) => [n.id, n]))
  const edges = new Map(cur.edges.map((e) => [e.id, e]))
  for (const n of next.nodes) {
    if (nodes.size < max || nodes.has(n.id)) nodes.set(n.id, n)
  }
  for (const e of next.edges) {
    if (nodes.has(e.source) && nodes.has(e.target)) edges.set(e.id, e)
  }
  return {
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    is_truncated: cur.is_truncated || next.is_truncated,
  }
}

function compactLabel(v: string) {
  return v.length > 30 ? `${v.slice(0, 27)}…` : v
}

function formatValue(v: unknown) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v).slice(0, 200)
  return String(v).slice(0, 200)
}

function toggleSet(value: string, setter: (u: (s: Set<string>) => Set<string>) => void) {
  setter((s) => {
    const next = new Set(s)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    return next
  })
}
