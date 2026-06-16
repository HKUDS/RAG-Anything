import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { ICON_MAP, getNodeType } from './nodeTypes'

const RUN_COLORS = {
  running: { bg: '#eff6ff', border: '#93c5fd', text: '#3b82f6', pulse: true },
  done: { bg: '#f0fdf4', border: '#86efac', text: '#22c55e', pulse: false },
  error: { bg: '#fff1f2', border: '#fda4af', text: '#f43f5e', pulse: false },
}

const handleStyle = {
  width: 12,
  height: 12,
  border: '2px solid #fff',
  transition: 'all 0.2s ease',
}

export default memo(function WorkflowNode({ data, selected }) {
  const def = getNodeType(data.nodeType)
  const Icon = def ? ICON_MAP[def.icon] : null
  const runStatus = data.runStatus
  const rc = RUN_COLORS[runStatus]

  return (
    <div
      className={`relative workflow-node ${rc?.pulse ? 'animate-pulse' : ''}`}
      style={{
        padding: '1px',
        borderRadius: 12,
        background: rc ? rc.border : selected ? def?.color : 'transparent',
        boxShadow: selected ? `0 0 0 2px ${def?.color}40` : '0 1px 3px rgba(0,0,0,0.08)',
      }}
    >
      <div
        className="flex items-center gap-2 px-3 py-2.5 rounded-[11px] min-w-[140px]"
        style={{ background: def?.bgColor || '#fff', border: `1px solid ${def?.borderColor || '#e5e7eb'}` }}
      >
        {/* Input handle */}
        {(def?.inputs ?? 1) > 0 && (
          <Handle
            type="target"
            position={Position.Left}
            className="workflow-handle"
            style={{ ...handleStyle, background: def?.color || '#94a3b8' }}
          />
        )}

        {/* Icon */}
        {Icon && (
          <div
            className="flex items-center justify-center w-7 h-7 rounded-lg flex-shrink-0"
            style={{ background: `${def?.color}18`, color: def?.color }}
          >
            <Icon size={14} />
          </div>
        )}

        {/* Label */}
        <span className="text-xs font-medium text-gray-700 truncate max-w-[120px]">
          {data.label || def?.label}
        </span>

        {/* Output handle */}
        {(def?.outputs ?? 1) > 0 && (
          <Handle
            type="source"
            position={Position.Right}
            className="workflow-handle"
            style={{ ...handleStyle, background: def?.color || '#94a3b8' }}
          />
        )}
      </div>
    </div>
  )
})
