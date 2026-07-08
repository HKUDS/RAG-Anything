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
// MiniMap 节点颜色由 nodeTypes 统一定义，保持单一数据源
import WorkflowNode from './WorkflowNode'
import { createDefaultNode, getNodeType } from './nodeTypes'

const nodeTypes = { custom: WorkflowNode }

const defaultEdgeOptions = {
  type: 'smoothstep',
  animated: true,
  style: { stroke: '#bcd3e8', strokeWidth: 2 },
  markerEnd: { type: MarkerType.ArrowClosed, color: '#bcd3e8', width: 16, height: 16 },
}

function EmptyState() {
  return (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
      <div className="text-center space-y-3">
        <GitBranch size={40} className="mx-auto text-cloud-300" />
        <p className="text-sm text-ink-muted font-medium">从左侧拖入节点开始编排</p>
        <p className="text-xs text-cloud-300">支持拖拽连线、缩放平移、自动布局</p>
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
        connectionLineStyle={{ stroke: '#bcd3e8', strokeWidth: 2, strokeDasharray: '6 4' }}
        fitView
        className="bg-cloud-200"
      >
        <Controls className="!rounded-xl !shadow-cloud-md !border-cloud-300" />
        {hasNodes && (
          <MiniMap
            className="!rounded-xl !shadow-cloud-md"
            nodeColor={(n) => getNodeType(n.data?.nodeType)?.color || '#557a95'}
          />
        )}
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#d6e5f2" />
      </ReactFlow>
    </div>
  )
}
