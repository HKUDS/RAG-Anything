import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { ICON_MAP, getNodeType } from './nodeTypes'

// 与品牌色保持一致的运行状态颜色：蓝色为运行中，绿色为完成，红色为错误
const RUN_COLORS = {
  running: { bg: '#f4f8fc', border: '#9dc6e5', text: '#5b9bd5', pulse: true },
  done:    { bg: '#f5f8f3', border: '#adc9a0', text: '#6b9e7a', pulse: false },
  error:   { bg: '#fdf5f6', border: '#ecb0bb', text: '#c9707e', pulse: false },
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
        boxShadow: selected ? `0 0 0 2px ${def?.color}40` : '0 1px 3px rgba(48,86,122,0.04), 0 1px 2px rgba(48,86,122,0.03)',
      }}
    >
      <div
        className="flex items-center gap-2 px-3 py-2.5 rounded-[11px] min-w-[140px]"
        style={{ background: def?.bgColor || '#fff', border: `1px solid ${def?.borderColor || '#d6e5f2'}` }}
      >
        {/* 输入连接点 */}
        {(def?.inputs ?? 1) > 0 && (
          <Handle
            type="target"
            position={Position.Left}
            className="workflow-handle"
            style={{ ...handleStyle, background: def?.color || '#557a95' }}
          />
        )}

        {/* 图标 */}
        {Icon && (
          <div
            className="flex items-center justify-center w-7 h-7 rounded-lg flex-shrink-0"
            style={{ background: `${def?.color}18`, color: def?.color }}
          >
            <Icon size={14} />
          </div>
        )}

        {/* 标签 */}
        <span className="text-xs font-medium text-ink-body truncate max-w-[120px]">
          {data.label || def?.label}
        </span>

        {/* 输出连接点 */}
        {(def?.outputs ?? 1) > 0 && (
          <Handle
            type="source"
            position={Position.Right}
            className="workflow-handle"
            style={{ ...handleStyle, background: def?.color || '#557a95' }}
          />
        )}
      </div>
    </div>
  )
})
