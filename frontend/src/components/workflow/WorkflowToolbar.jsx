import { Save, FolderOpen, FilePlus, ZoomIn, ZoomOut, Maximize2, LayoutGrid, Undo2, Redo2, Play, Loader2 } from 'lucide-react'

export default function WorkflowToolbar({
  workflowName, onNameChange, onNew, onSave, onLoad,
  onAutoLayout, onFitView, onZoomIn, onZoomOut,
  onUndo, onRedo, onRun, saving, running, isDirty, zoomLevel, hasNodes,
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-white border-b border-warm-200 flex-shrink-0">
      {/* Workflow name */}
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          value={workflowName}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="未命名工作流"
          className="text-sm font-medium text-warm-800 bg-transparent border-none outline-none
                     focus:bg-warm-50 rounded-lg px-2 py-1 w-48 placeholder:text-warm-400"
        />
        {isDirty && (
          <span className="w-2 h-2 rounded-full bg-amber-400 flex-shrink-0" title="有未保存的修改" />
        )}
      </div>

      <div className="w-px h-5 bg-warm-200" />

      {/* Actions */}
      <button onClick={onNew} title="新建 (未保存时弹出确认)" className="toolbar-btn">
        <FilePlus size={16} />
      </button>
      <button onClick={onSave} disabled={saving} title="保存 (Ctrl+S)" className="toolbar-btn">
        <Save size={16} />
      </button>
      <button onClick={onLoad} title="加载" className="toolbar-btn">
        <FolderOpen size={16} />
      </button>

      <div className="w-px h-5 bg-warm-200" />

      {/* Undo/Redo */}
      <button onClick={onUndo} title="撤销 (Ctrl+Z)" className="toolbar-btn">
        <Undo2 size={15} />
      </button>
      <button onClick={onRedo} title="重做 (Ctrl+Y)" className="toolbar-btn">
        <Redo2 size={15} />
      </button>

      <div className="w-px h-5 bg-warm-200" />

      {/* Run */}
      {hasNodes && (
        <button
          onClick={onRun}
          disabled={running}
          title="运行工作流"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                     bg-emerald-500 text-white hover:bg-emerald-600
                     disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} className="ml-0.5" />}
          {running ? '运行中' : '运行'}
        </button>
      )}

      {/* Layout & View */}
      <button onClick={onAutoLayout} title="自动布局" className="toolbar-btn">
        <LayoutGrid size={16} />
      </button>
      <button onClick={onFitView} title="适应画布" className="toolbar-btn">
        <Maximize2 size={16} />
      </button>

      {/* Zoom group */}
      <div className="flex items-center gap-1 bg-warm-50 rounded-lg px-1">
        <button onClick={onZoomOut} title="缩小" className="toolbar-btn !w-7 !h-7">
          <ZoomOut size={15} />
        </button>
        <span className="text-2xs font-mono text-warm-500 w-9 text-center tabular-nums select-none">
          {zoomLevel}%
        </span>
        <button onClick={onZoomIn} title="放大" className="toolbar-btn !w-7 !h-7">
          <ZoomIn size={15} />
        </button>
      </div>
    </div>
  )
}
