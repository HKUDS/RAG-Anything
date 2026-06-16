import { NODE_TYPES, ICON_MAP } from './nodeTypes'

export default function NodePalette() {
  const onDragStart = (e, typeId) => {
    e.dataTransfer.setData('application/workflow-node', typeId)
    e.dataTransfer.effectAllowed = 'move'
  }

  return (
    <div className="w-52 flex-shrink-0 bg-white border-r border-warm-200 p-3 overflow-y-auto">
      <h3 className="text-xs font-semibold text-warm-500 uppercase tracking-wider mb-3 px-1">
        节点类型
      </h3>
      <div className="space-y-1.5">
        {NODE_TYPES.map((def) => {
          const Icon = ICON_MAP[def.icon]
          return (
            <div
              key={def.id}
              draggable
              onDragStart={(e) => onDragStart(e, def.id)}
              className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl cursor-grab active:cursor-grabbing
                         transition-all hover:shadow-sm border border-transparent hover:border-warm-200 bg-warm-50 hover:bg-white"
              style={{ '--node-color': def.color }}
            >
              <div
                className="flex items-center justify-center w-7 h-7 rounded-lg flex-shrink-0"
                style={{ background: `${def.color}18`, color: def.color }}
              >
                <Icon size={14} />
              </div>
              <span className="text-xs font-medium text-warm-700">{def.label}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
