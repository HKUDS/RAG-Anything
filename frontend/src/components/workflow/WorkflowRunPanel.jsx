import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronUp, ChevronDown, Clock, CheckCircle2, XCircle, History } from 'lucide-react'

export default function WorkflowRunPanel({ runs, currentRun, onSelectRun }) {
  const [collapsed, setCollapsed] = useState(false)

  if (!currentRun && runs.length === 0) return null

  const statusIcon = currentRun?.status === 'completed' ? (
    <CheckCircle2 size={14} className="text-emerald-500" />
  ) : currentRun?.status === 'failed' ? (
    <XCircle size={14} className="text-rose-500" />
  ) : (
    <Clock size={14} className="text-amber-500" />
  )

  const nodeStatus = (nodeId) => {
    const nr = currentRun?.node_results?.find(r => r.node_id === nodeId)
    return nr?.status
  }

  return (
    <div className="border-t border-cloud-300 bg-white flex-shrink-0">
      {/* 头部栏 */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-4 py-2 hover:bg-cloud-200 transition-colors"
      >
        <div className="flex items-center gap-2 text-xs">
          <span className="font-semibold text-ink-body">输出</span>
          {currentRun && (
            <>
              {statusIcon}
              <span className="text-ink-muted">
                {currentRun.status === 'completed' ? '完成' : currentRun.status === 'failed' ? '失败' : '运行中'}
              </span>
              <span className="text-ink-muted">· {currentRun.started_at ? new Date(currentRun.started_at).toLocaleTimeString() : ''}</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* 历史记录下拉框 */}
          {runs.length > 1 && (
            <select
              value={currentRun?.run_id || ''}
              onChange={(e) => onSelectRun(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              className="text-2xs border border-cloud-300 rounded-lg px-2 py-1 bg-cloud-200 text-ink-body"
            >
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {new Date(r.started_at).toLocaleTimeString()} - {r.status === 'completed' ? '完成' : r.status === 'failed' ? '失败' : '运行中'} {r.workflow_name}
                </option>
              ))}
            </select>
          )}
          {collapsed ? <ChevronUp size={14} className="text-ink-muted" /> : <ChevronDown size={14} className="text-ink-muted" />}
        </div>
      </button>

      {/* 面板主体 */}
      <AnimatePresence>
        {!collapsed && currentRun && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-3 max-h-60 overflow-y-auto">
              {/* 节点结果 */}
              {currentRun.node_results?.map((nr) => (
                <div key={nr.node_id} className="flex items-start gap-2 text-xs">
                  <div
                    className={`w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 ${
                      nr.status === 'done' ? 'bg-emerald-400' :
                      nr.status === 'error' ? 'bg-rose-400' :
                      nr.status === 'running' ? 'bg-blue-400 animate-pulse' : 'bg-cloud-300'
                    }`}
                  />
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-ink-body">{nr.node_id}</span>
                    <span className={`ml-2 ${
                      nr.status === 'done' ? 'text-emerald-600' :
                      nr.status === 'error' ? 'text-rose-600' : 'text-ink-muted'
                    }`}>
                      {nr.status === 'done' ? '完成' : nr.status === 'error' ? '失败' : nr.status}
                    </span>
                    {nr.data?.duration_ms != null && (
                      <span className="ml-2 text-ink-muted">{nr.data.duration_ms}ms</span>
                    )}
                    {nr.data?.search_mode && (
                      <span className={`ml-2 px-1.5 py-0.5 rounded text-2xs font-medium ${
                        nr.data.search_mode === 'in_memory'
                          ? 'bg-sky-50 text-sky-600'
                          : 'bg-amber-100 text-amber-600'
                      }`}>
                        {nr.data.search_mode === 'in_memory' ? '内存检索' : '知识库'}
                      </span>
                    )}
                    {nr.data?.error && (
                      <p className="text-rose-500 mt-0.5">{nr.data.error}</p>
                    )}
                  </div>
                </div>
              ))}

              {/* 最终输出 */}
              {currentRun.final_output && currentRun.status === 'completed' && (
                <div className="mt-3 p-3 rounded-xl bg-cloud-200 border border-cloud-200">
                  <pre className="text-xs text-ink-body whitespace-pre-wrap font-sans leading-relaxed">
                    {currentRun.final_output}
                  </pre>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
