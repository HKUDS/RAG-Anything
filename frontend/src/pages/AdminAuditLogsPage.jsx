import { useState, useEffect, useCallback } from 'react'
import { Activity, Database, Loader2, ScrollText, ShieldOff, UserPlus, UserCog, Trash2, ShieldAlert } from 'lucide-react'
import Pagination from '../components/Pagination'
import { api } from '../utils/api'

const AUTH_TOKEN = () => {
  const saved = localStorage.getItem('raganything_auth')
  return saved ? JSON.parse(saved).token : ''
}

const ACTION_LABELS = {
  'user.create': '创建用户',
  'user.update': '更新用户',
  'user.delete': '删除用户',
  'user.role_change': '角色变更',
  'permission.denied': '权限拒绝',
}

// 操作类型的颜色和图标映射
const ACTION_META = {
  'user.create':      { color: 'bg-sage-50 text-sage-600 border-sage-200 dark:bg-sage-900/20 dark:text-sage-400 dark:border-sage-800/30', icon: UserPlus },
  'user.update':      { color: 'bg-sky-50 text-sky-600 border-sky-200', icon: UserCog },
  'user.delete':      { color: 'bg-rose-50 text-rose-600 border-rose-200', icon: Trash2 },
  'user.role_change': { color: 'bg-amber-50 text-amber-600 border-amber-200', icon: ShieldAlert },
  'permission.denied':{ color: 'bg-rose-50 text-rose-600 border-rose-200 dark:bg-rose-900/20 dark:text-rose-400 dark:border-rose-800/30', icon: ShieldOff },
}

// 角色名称映射（与全局 ROLE_META 保持一致）
const ROLE_LABELS = {
  super_admin: '超级管理员', admin: '管理员', dept_admin: '系部管理员',
  teacher: '主讲教师', assistant: '助理教师', student: '学生',
}

/** 将审计详情 JSON 渲染为可读的中文描述 */
function formatDetails(action, details) {
  if (!details || typeof details !== 'object') return String(details || '—')

  switch (action) {
    case 'user.create':
      return `创建用户 ${details.username || '?'}（${ROLE_LABELS[details.role_name] || details.role_name || '角色#' + details.role_id}）`
    case 'user.role_change': {
      const before = ROLE_LABELS[details.before_role_name] || details.before_role_name || '角色#' + details.before?.role_id
      const after = ROLE_LABELS[details.after_role_name] || details.after_role_name || '角色#' + details.after?.role_id
      return `${before} → ${after}（由 ${ROLE_LABELS[details.actor_role] || details.actor_role || '?'} 操作）`
    }
    case 'user.update': {
      const fields = details.changed_fields?.map(f => {
        const FIELD_MAP = { username: '用户名', email: '邮箱', is_active: '状态', password_hash: '密码', role_id: '角色' }
        return FIELD_MAP[f] || f
      }).join('、') || '未知字段'
      return `修改了：${fields}`
    }
    case 'user.delete':
      return `删除用户 ${details.username || '?'}（${ROLE_LABELS[details.actor_role] || '?'} 操作）`
    case 'permission.denied':
      return `尝试访问 ${details.method} ${details.endpoint}，需要权限 ${details.required_permission}（当前角色：${ROLE_LABELS[details.user_role] || details.user_role}）`
    default:
      return JSON.stringify(details).substring(0, 80)
  }
}

export default function AdminAuditLogsPage() {
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [actionFilter, setActionFilter] = useState('')
  const [auditHealth, setAuditHealth] = useState(null)

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
  useEffect(() => {
    api.getAuditHealth()
      .then(setAuditHealth)
      .catch(err => setAuditHealth({ status: 'degraded', error: err.message }))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={24} className="animate-spin text-sky-500" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="page-header page-header-divider">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-sky-50 dark:bg-sky-900/40 flex items-center justify-center">
            <ScrollText size={18} className="text-sky-500 dark:text-sky-400" />
          </div>
          <div>
            <h2 className="page-title">审计日志</h2>
            <p className="page-subtitle">共 {total} 条记录</p>
          </div>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-600 text-xs">{error}</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className={`card p-4 ${auditHealth?.status === 'degraded' ? 'border-amber-200 bg-amber-50' : ''}`}>
          <div className="flex items-center gap-2 text-xs text-ink-muted mb-1">
            <Activity size={14} /> 审计状态
          </div>
          <p className={`text-lg font-semibold ${auditHealth?.status === 'degraded' ? 'text-amber-600' : 'text-sky-600'}`}>
            {auditHealth?.status || '检测中'}
          </p>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-2 text-xs text-ink-muted mb-1">
            <Database size={14} /> 审计后端
          </div>
          <p className="text-lg font-semibold text-ink-primary">{auditHealth?.backend || '—'}</p>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-2 text-xs text-ink-muted mb-1">
            <ScrollText size={14} /> 记录总数
          </div>
          <p className="text-lg font-semibold text-ink-primary">{(auditHealth?.total_records ?? total).toLocaleString()}</p>
          {auditHealth?.error && <p className="text-xs text-amber-600 mt-1 truncate">{auditHealth.error}</p>}
        </div>
      </div>

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
              <tr className="border-b border-cloud-300/60 text-left">
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">ID</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">操作人</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">操作类型</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">目标用户</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">详情</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">IP</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">时间</th>
              </tr>
            </thead>
            <tbody>
              {logs.map(l => {
                const meta = ACTION_META[l.action] || { color: 'bg-cloud-50 text-ink-muted border-cloud-200 dark:bg-sky-900/20 dark:text-cloud-500 dark:border-sky-800/30', icon: null }
                const ActionIcon = meta.icon
                return (
                <tr key={l.id} className="border-b border-cloud-200 hover:bg-cloud-200/50 transition-colors">
                  <td className="py-2 px-3 text-xs text-ink-muted font-mono">{l.id}</td>
                  <td className="py-2 px-3 text-xs text-ink-body font-medium">#{l.actor_id}</td>
                  <td className="py-2 px-3">
                    <span className={`text-2xs px-1.5 py-0.5 rounded-lg border inline-flex items-center gap-1 ${meta.color}`}>
                      {ActionIcon && <ActionIcon size={10} />}
                      {ACTION_LABELS[l.action] || l.action}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-xs text-ink-muted">{l.target_user_id ? `#${l.target_user_id}` : '—'}</td>
                  <td className="py-2 px-3 text-xs text-ink-muted max-w-[280px] truncate" title={typeof l.details === 'object' ? JSON.stringify(l.details) : String(l.details || '')}>
                    {formatDetails(l.action, l.details)}
                  </td>
                  <td className="py-2 px-3 text-xs text-ink-muted font-mono">{l.ip_address || '—'}</td>
                  <td className="py-2 px-3 text-xs text-ink-muted whitespace-nowrap">{l.created_at?.replace('T', ' ').substring(0, 16)}</td>
                </tr>
                )
              })}
              {logs.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-ink-muted text-sm">暂无审计日志</td></tr>
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
