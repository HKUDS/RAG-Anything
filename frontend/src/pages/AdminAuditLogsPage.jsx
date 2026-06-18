import { useState, useEffect, useCallback } from 'react'
import { Loader2, ScrollText, Eye } from 'lucide-react'
import Pagination from '../components/Pagination'

const AUTH_TOKEN = () => {
  const saved = localStorage.getItem('raganything_auth')
  return saved ? JSON.parse(saved).token : ''
}

const ACTION_LABELS = {
  'user.create': '创建用户',
  'user.update': '更新用户',
  'user.delete': '删除用户',
  'user.role_change': '角色变更',
}

export default function AdminAuditLogsPage() {
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [actionFilter, setActionFilter] = useState('')

  const loadLogs = useCallback(async () => {
    try {
      const token = AUTH_TOKEN()
      const params = new URLSearchParams({ page, page_size: 20 })
      if (actionFilter) params.set('action', actionFilter)
      const res = await fetch(`/api/admin/audit-logs?${params}`, {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setLogs(data.logs || [])
      setTotal(data.total || 0)
      setTotalPages(data.total_pages || 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [page, actionFilter])

  useEffect(() => { loadLogs() }, [loadLogs])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={24} className="animate-spin text-coral-500" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="page-header page-header-divider">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center">
            <ScrollText size={18} className="text-indigo-600" />
          </div>
          <div>
            <h2 className="page-title">📋 审计日志</h2>
            <p className="page-subtitle">共 {total} 条记录</p>
          </div>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-600 text-xs">{error}</div>
      )}

      <div className="flex items-center gap-3">
        <select className="input-field text-sm py-2" value={actionFilter} onChange={e => { setActionFilter(e.target.value); setPage(1) }}>
          <option value="">全部操作类型</option>
          {Object.entries(ACTION_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-warm-200/60 text-left">
                <th className="py-2.5 px-3 text-xs text-warm-500 font-medium">ID</th>
                <th className="py-2.5 px-3 text-xs text-warm-500 font-medium">操作人</th>
                <th className="py-2.5 px-3 text-xs text-warm-500 font-medium">操作类型</th>
                <th className="py-2.5 px-3 text-xs text-warm-500 font-medium">目标用户</th>
                <th className="py-2.5 px-3 text-xs text-warm-500 font-medium">详情</th>
                <th className="py-2.5 px-3 text-xs text-warm-500 font-medium">IP</th>
                <th className="py-2.5 px-3 text-xs text-warm-500 font-medium">时间</th>
              </tr>
            </thead>
            <tbody>
              {logs.map(l => (
                <tr key={l.id} className="border-b border-warm-100 hover:bg-warm-50/50 transition-colors">
                  <td className="py-2 px-3 text-xs text-warm-500 font-mono">{l.id}</td>
                  <td className="py-2 px-3 text-xs text-warm-700 font-medium">#{l.actor_id}</td>
                  <td className="py-2 px-3">
                    <span className="text-[10px] px-1.5 py-0.5 rounded-lg bg-indigo-50 text-indigo-600 border border-indigo-200">
                      {ACTION_LABELS[l.action] || l.action}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-xs text-warm-500">#{l.target_user_id || '—'}</td>
                  <td className="py-2 px-3 text-xs text-warm-500 max-w-[200px] truncate">
                    {typeof l.details === 'object' ? JSON.stringify(l.details).substring(0, 60) + '...' : String(l.details || '—')}
                  </td>
                  <td className="py-2 px-3 text-xs text-warm-500 font-mono">{l.ip_address || '—'}</td>
                  <td className="py-2 px-3 text-xs text-warm-500">{l.created_at?.replace('T', ' ').substring(0, 16)}</td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-warm-400 text-sm">暂无审计日志</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="px-3 pb-2">
          <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
        </div>
      </div>
    </div>
  )
}
