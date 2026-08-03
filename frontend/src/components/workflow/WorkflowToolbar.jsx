import { Save, FolderOpen, FilePlus, ZoomIn, ZoomOut, Maximize2, LayoutGrid, Undo2, Redo2, Play, Loader2, MessageCircle } from 'lucide-react'

export default function WorkflowToolbar({
  workflowName, onNameChange, onNew, onSave, onLoad,
  onAutoLayout, onFitView, onZoomIn, onZoomOut,
  onUndo, onRedo, onRun, saving, running, isDirty, zoomLevel, hasNodes,
  queryText, onQueryTextChange, canEdit = false,
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-white border-b border-cloud-300 flex-shrink-0">
      {/* 工作流名称 */}
      <div className="flex items-center gap-1.5">
        {canEdit ? <input
          type="text"
          value={workflowName}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="未命名工作流"
          className="text-sm font-medium text-ink-primary bg-transparent border-none outline-none
                     focus:bg-cloud-200 rounded-lg px-2 py-1 w-48 placeholder:text-ink-muted"
        /> : <output className="text-sm font-medium text-ink-primary px-2 py-1 w-48 truncate">{workflowName}</output>}
        {canEdit && isDirty && (
          <span className="w-2 h-2 rounded-full bg-amber-400 flex-shrink-0" title="有未保存的修改" />
        )}
      </div>

      <div className="w-px h-5 bg-cloud-300" />

      {/* 操作 */}
      {canEdit && <button onClick={onNew} title="新建 (未保存时弹出确认)" className="toolbar-btn"><FilePlus size={16} /></button>}
      {canEdit && <button onClick={onSave} disabled={saving} title="保存 (Ctrl+S)" className="toolbar-btn"><Save size={16} /></button>}
      <button onClick={onLoad} title="加载" className="toolbar-btn">
        <FolderOpen size={16} />
      </button>

      <div className="w-px h-5 bg-cloud-300" />

      {/* 撤销/重做 */}
      {canEdit && <button onClick={onUndo} title="撤销 (Ctrl+Z)" className="toolbar-btn"><Undo2 size={15} /></button>}
      {canEdit && <button onClick={onRedo} title="重做 (Ctrl+Y)" className="toolbar-btn"><Redo2 size={15} /></button>}

      <div className="w-px h-5 bg-cloud-300" />

      <div className="flex-1" />

      {/* 运行时问题输入 */}
      {canEdit && hasNodes && (
        <div className="flex items-center gap-1.5 flex-1 max-w-md">
          <MessageCircle size={14} className="text-ink-muted flex-shrink-0" />
          <input
            type="text"
            value={queryText || ''}
            onChange={(e) => onQueryTextChange?.(e.target.value)}
            placeholder="输入问题后运行..."
            onKeyDown={(e) => { if (e.key === 'Enter' && !running) onRun?.() }}
            disabled={running}
            className="flex-1 text-xs px-3 py-1.5 rounded-lg border border-cloud-300 bg-white
                       focus:outline-none focus:ring-2 focus:ring-sky-200 focus:border-sky-400
                       text-ink-body placeholder:text-cloud-400 disabled:opacity-50"
          />
        </div>
      )}

      {/* 运行 */}
      {canEdit && hasNodes && (
        <button
          onClick={onRun}
          disabled={running}
          title="运行工作流 (Enter 快捷运行)"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                     bg-emerald-500 text-white hover:bg-emerald-600
                     disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} className="ml-0.5" />}
          {running ? '运行中' : '运行'}
        </button>
      )}

      {/* 布局与视图 */}
      {canEdit && <button onClick={onAutoLayout} title="自动布局" className="toolbar-btn"><LayoutGrid size={16} /></button>}
      <button onClick={onFitView} title="适应画布" className="toolbar-btn">
        <Maximize2 size={16} />
      </button>

      {/* 缩放控件组 */}
      <div className="flex items-center gap-1 bg-cloud-200 rounded-lg px-1">
        <button onClick={onZoomOut} title="缩小" className="toolbar-btn !w-7 !h-7">
          <ZoomOut size={15} />
        </button>
        <span className="text-2xs font-mono text-ink-muted w-9 text-center tabular-nums select-none">
          {zoomLevel}%
        </span>
        <button onClick={onZoomIn} title="放大" className="toolbar-btn !w-7 !h-7">
          <ZoomIn size={15} />
        </button>
      </div>
    </div>
  )
}
