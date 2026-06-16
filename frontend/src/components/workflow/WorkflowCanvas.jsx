import { useCallback, useRef, useEffect } from 'react'
import {
  ReactFlow,
  addEdge,
  useNodesState,
  useEdgesState,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import WorkflowNode from './WorkflowNode'
import { createDefaultNode } from './nodeTypes'

const nodeTypes = { custom: WorkflowNode }

const defaultEdgeOptions = {
  type: 'smoothstep',
  animated: true,
  style: { stroke: '#94a3b8', strokeWidth: 2 },
  markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8', width: 16, height: 16 },
}

export default function WorkflowCanvas({ nodes, setNodes, edges, setEdges, onNodeClick }) {
  const reactFlowWrapper = useRef(null)
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(nodes)
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(edges)

  // Sync external state in
  useEffect(() => {
    if (nodes !== rfNodes && nodes.length !== rfNodes.length) setRfNodes(nodes)
  }, [nodes])

  useEffect(() => {
    if (edges !== rfEdges && edges.length !== rfEdges.length) setRfEdges(edges)
  }, [edges])

  // Sync state out
  useEffect(() => { setNodes(rfNodes) }, [rfNodes])
  useEffect(() => { setEdges(rfEdges) }, [rfEdges])

  const onConnect = useCallback(
    (connection) => setRfEdges((eds) => addEdge({ ...connection, ...defaultEdgeOptions }, eds)),
    [setRfEdges]
  )

  // Drag from palette
  const onDragOver = useCallback((e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback(
    (e) => {
      e.preventDefault()
      const typeId = e.dataTransfer.getData('application/workflow-node')
      if (!typeId || !reactFlowWrapper.current) return
      const bounds = reactFlowWrapper.current.getBoundingClientRect()
      const position = {
        x: e.clientX - bounds.left - 70,
        y: e.clientY - bounds.top - 25,
      }
      const newNode = createDefaultNode(typeId, position)
      if (newNode) setRfNodes((nds) => [...nds, newNode])
    },
    [setRfNodes]
  )

  // Keyboard delete
  const onKeyDown = useCallback(
    (e) => {
      if (e.key === 'Delete' || e.key === 'Backspace') {
        // ReactFlow handles node/edge deletion internally via onNodesChange/onEdgesChange
        // when deleteKeyCode is set
      }
    },
    []
  )

  return (
    <div ref={reactFlowWrapper} className="flex-1 h-full" onDrop={onDrop} onDragOver={onDragOver} onKeyDown={onKeyDown} tabIndex={0}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, node) => onNodeClick?.(node)}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        deleteKeyCode={['Delete', 'Backspace']}
        fitView
        className="bg-warm-50"
      >
        <Controls className="!rounded-xl !shadow-warm-md !border-warm-200" />
        <MiniMap
          className="!rounded-xl !shadow-warm-md"
          nodeColor={(n) => {
            const def = n.data?.nodeType
            const colors = { document_input: '#3b82f6', text_splitter: '#22c55e', embedding: '#a855f7', retriever: '#f59e0b', llm_answer: '#f43f5e', output: '#6b7280' }
            return colors[def] || '#94a3b8'
          }}
        />
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#e2e8f0" />
      </ReactFlow>
    </div>
  )
}
