import { AlertTriangle, Database, RotateCcw } from 'lucide-react'

export default function AutoRepairKBState({ error, onRetry }) {
  if (error) {
    return (
      <div className="py-12 text-center" role="alert">
        <AlertTriangle size={32} className="mx-auto text-rose-500" />
        <p className="mt-3 text-sm font-medium text-ink-body">知识库列表加载失败</p>
        <p className="mx-auto mt-1 max-w-md text-xs text-ink-muted">{error}</p>
        <button type="button" className="btn-secondary mt-4" onClick={onRetry}>
          <RotateCcw size={14} />重新加载
        </button>
      </div>
    )
  }

  return (
    <div className="py-12 text-center">
      <Database size={36} className="mx-auto text-cloud-300" />
      <p className="mt-3 text-sm font-medium text-ink-body">暂无可用知识库</p>
      <p className="mt-1 text-xs text-ink-muted">当前没有可查看的汽修知识内容。</p>
    </div>
  )
}
