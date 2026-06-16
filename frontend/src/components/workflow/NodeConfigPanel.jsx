import { X } from 'lucide-react'
import { getNodeType } from './nodeTypes'

export default function NodeConfigPanel({ node, onClose, onUpdate }) {
  if (!node) return null

  const def = getNodeType(node.data?.nodeType)
  if (!def) return null

  const handleChange = (key, value) => {
    onUpdate?.(node.id, { ...node.data, [key]: value })
  }

  return (
    <div className="w-64 flex-shrink-0 bg-white border-l border-warm-200 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-warm-100">
        <h3 className="text-sm font-semibold text-warm-700">节点配置</h3>
        <button onClick={onClose} className="p-1 rounded-lg hover:bg-warm-100 text-warm-400 transition-colors">
          <X size={16} />
        </button>
      </div>

      {/* Node type indicator */}
      <div className="px-4 py-2.5 border-b border-warm-100 flex items-center gap-2">
        <div
          className="w-2.5 h-2.5 rounded-full flex-shrink-0"
          style={{ background: def.color }}
        />
        <span className="text-xs text-warm-500">{def.label}</span>
      </div>

      {/* Config form */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {def.configFields.map((field) => (
          <div key={field.key}>
            <label className="block text-xs font-medium text-warm-600 mb-1.5">
              {field.label}
            </label>

            {field.type === 'select' ? (
              <select
                value={node.data[field.key] ?? field.default}
                onChange={(e) => handleChange(field.key, e.target.value)}
                className="w-full text-xs px-3 py-2 rounded-lg border border-warm-200 bg-white
                           focus:outline-none focus:ring-2 focus:ring-coral-200 focus:border-coral-300
                           text-warm-700"
              >
                {field.options.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            ) : field.type === 'textarea' ? (
              <textarea
                value={node.data[field.key] ?? field.default}
                onChange={(e) => handleChange(field.key, e.target.value)}
                rows={4}
                placeholder="输入系统提示词..."
                className="w-full text-xs px-3 py-2 rounded-lg border border-warm-200
                           focus:outline-none focus:ring-2 focus:ring-coral-200 focus:border-coral-300
                           text-warm-700 resize-y font-mono"
              />
            ) : field.type === 'number' ? (
              <input
                type="number"
                value={node.data[field.key] ?? field.default}
                onChange={(e) => handleChange(field.key, field.type === 'number' ? Number(e.target.value) : e.target.value)}
                min={field.min}
                max={field.max}
                step={field.step}
                className="w-full text-xs px-3 py-2 rounded-lg border border-warm-200
                           focus:outline-none focus:ring-2 focus:ring-coral-200 focus:border-coral-300
                           text-warm-700"
              />
            ) : (
              <input
                type={field.type}
                value={node.data[field.key] ?? field.default}
                onChange={(e) => handleChange(field.key, e.target.value)}
                className="w-full text-xs px-3 py-2 rounded-lg border border-warm-200
                           focus:outline-none focus:ring-2 focus:ring-coral-200 focus:border-coral-300
                           text-warm-700"
              />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
