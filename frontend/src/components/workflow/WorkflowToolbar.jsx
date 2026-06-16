import { Save, FolderOpen, FilePlus, ZoomIn, ZoomOut, Maximize2, LayoutGrid } from 'lucide-react'

export default function WorkflowToolbar({
  workflowName,
  onNameChange,
  onNew,
  onSave,
  onLoad,
  onAutoLayout,
  onFitView,
  onZoomIn,
  onZoomOut,
  saving,
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-white border-b border-warm-200 flex-shrink-0">
      {/* Workflow name */}
      <input
        type="text"
        value={workflowName}
        onChange={(e) => onNameChange(e.target.value)}
        placeholder="未命名工作流"
        className="text-sm font-medium text-warm-800 bg-transparent border-none outline-none
                   focus:bg-warm-50 rounded-lg px-2 py-1 w-48 placeholder:text-warm-400"
      />

      <div className="w-px h-5 bg-warm-200" />

      {/* Actions */}
      <button onClick={onNew} title="新建" className="toolbar-btn">
        <FilePlus size={16} />
      </button>
      <button onClick={onSave} disabled={saving} title="保存" className="toolbar-btn">
        <Save size={16} />
      </button>
      <button onClick={onLoad} title="加载" className="toolbar-btn">
        <FolderOpen size={16} />
      </button>

      <div className="w-px h-5 bg-warm-200" />

      {/* Layout & View */}
      <button onClick={onAutoLayout} title="自动布局" className="toolbar-btn">
        <LayoutGrid size={16} />
      </button>
      <button onClick={onFitView} title="适应画布" className="toolbar-btn">
        <Maximize2 size={16} />
      </button>
      <button onClick={onZoomIn} title="放大" className="toolbar-btn">
        <ZoomIn size={16} />
      </button>
      <button onClick={onZoomOut} title="缩小" className="toolbar-btn">
        <ZoomOut size={16} />
      </button>
    </div>
  )
}
