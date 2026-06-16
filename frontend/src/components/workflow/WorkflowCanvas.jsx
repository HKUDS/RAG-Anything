import { useCallback, useRef } from 'react'
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { GitBranch } from 'lucide-react'
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

function EmptyState() {
  return (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
      <div className="text-center space-y-3">
        <GitBranch size={40} className="mx-auto text-warm-300" />
        <p className="text-sm text-warm-400 font-medium">从左侧拖入节点开始编排</p>
        <p className="text-xs text-warm-300">支持拖拽连线、缩放平移、自动布局</p>
      </div>
    </div>
  )
}

export default function WorkflowCanvas({
  nodes, edges, onNodesChange, onEdgesChange, onConnect,
  onNodeClick, onDropNode, onPaneClick,
}) {
  const reactFlowWrapper = useRef(null)
  const hasNodes = nodes.length > 0

  const handleConnect = useCallback(
    (connection) => onConnect(connection),
    [onConnect]
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
    <div ref={reactFlowWrapper} className="flex-1 h-full relative" onDrop={onDrop} onDragOver={onDragOver}>
      {!hasNodes && <EmptyState />}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
        onNodeClick={(_, node) => onNodeClick?.(node)}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        deleteKeyCode={['Delete', 'Backspace']}
        connectionLineStyle={{ stroke: '#94a3b8', strokeWidth: 2, strokeDasharray: '6 4' }}
        fitView
        className="bg-warm-50"
      >
        <Controls className="!rounded-xl !shadow-warm-md !border-warm-200" />
        {hasNodes && (
          <MiniMap
            className="!rounded-xl !shadow-warm-md"
            nodeColor={(n) => NODE_COLORS[n.data?.nodeType] || '#94a3b8'}
          />
        )}
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#e2e8f0" />
      </ReactFlow>
    </div>
  )
}
