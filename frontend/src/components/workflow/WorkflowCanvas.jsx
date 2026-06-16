import { useCallback, useRef } from 'react'
import {
  ReactFlow,
  addEdge,
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

const NODE_COLORS = {
  document_input: '#3b82f6', text_splitter: '#22c55e', embedding: '#a855f7',
  retriever: '#f59e0b', llm_answer: '#f43f5e', output: '#6b7280',
}

export default function WorkflowCanvas({
  nodes, edges, onNodesChange, onEdgesChange, onConnect,
  onNodeClick, onDropNode,
}) {
  const reactFlowWrapper = useRef(null)

  const handleConnect = useCallback(
    (connection) => onConnect(addEdge({ ...connection, ...defaultEdgeOptions }, edges)),
    [onConnect, edges]
  )

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
      const position = { x: e.clientX - bounds.left - 70, y: e.clientY - bounds.top - 25 }
      const newNode = createDefaultNode(typeId, position)
      if (newNode) onDropNode(newNode)
    },
    [onDropNode]
  )

  return (
    <div ref={reactFlowWrapper} className="flex-1 h-full" onDrop={onDrop} onDragOver={onDragOver}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
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
          nodeColor={(n) => NODE_COLORS[n.data?.nodeType] || '#94a3b8'}
        />
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#e2e8f0" />
      </ReactFlow>
    </div>
  )
}
