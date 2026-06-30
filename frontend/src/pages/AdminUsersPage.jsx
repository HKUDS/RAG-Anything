import { useState, useEffect, useCallback } from 'react'
import { Trash2, Edit3, Loader2, Shield, User, Users, Search, UserPlus, Filter } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import Pagination from '../components/Pagination'
import CreateUserModal from '../components/CreateUserModal'
import EditUserModal from '../components/EditUserModal'

const AUTH_TOKEN = () => {
  const saved = localStorage.getItem('raganything_auth')
  return saved ? JSON.parse(saved).token : ''
}

async function authFetch(url, options = {}) {
  const token = AUTH_TOKEN()
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`, ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

const ROLE_COLORS = {
  super_admin: 'bg-rose-50 text-rose-600 border-rose-200 dark:bg-rose-900/20 dark:text-rose-400 dark:border-rose-800/30',
  admin:       'bg-rose-50 text-rose-600 border-rose-200 dark:bg-rose-900/20 dark:text-rose-400 dark:border-rose-800/30',
  dept_admin:  'bg-amber-50 text-amber-600 border-amber-200 dark:bg-amber-900/20 dark:text-amber-400 dark:border-amber-800/30',
  teacher:     'bg-sky-50 text-sky-600 border-sky-200 dark:bg-sky-900/20 dark:text-sky-400 dark:border-sky-800/30',
  assistant:   'bg-sage-50 text-sage-600 border-sage-200 dark:bg-sage-900/20 dark:text-sage-400 dark:border-sage-800/30',
  student:     'bg-cloud-50 text-ink-muted border-cloud-200 dark:bg-sky-900/10 dark:text-cloud-500 dark:border-sky-800/30',
}

const ROLE_LABELS = {
  super_admin: '超级管理员',
  admin:       '管理员',
  dept_admin:  '系部管理员',
  teacher:     '主讲教师',
  assistant:   '助理教师',
  student:     '学生',
}

export default function AdminUsersPage() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [roles, setRoles] = useState([])
  const [deletingId, setDeletingId] = useState(null)

  // Modals
  const [showCreate, setShowCreate] = useState(false)
  const [editUser, setEditUser] = useState(null)

  const loadUsers = useCallback(async () => {
    try {
      const params = new URLSearchParams({ page, page_size: 20 })
      if (search) params.set('search', search)
      if (roleFilter) params.set('role', roleFilter)
      if (statusFilter) params.set('status', statusFilter)
      const data = await authFetch(`/api/admin/users?${params}`)
      setUsers(data.users || [])
      setTotal(data.total || 0)
      setTotalPages(data.total_pages || 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [page, search, roleFilter, statusFilter])

  const loadRoles = useCallback(async () => {
    try {
      const data = await authFetch('/api/admin/roles')
      setRoles(data.roles || [])
    } catch (_) {}
  }, [])

  useEffect(() => { loadUsers() }, [loadUsers])
  useEffect(() => { loadRoles() }, [loadRoles])

  const handleDelete = async (userId) => {
    if (userId === me?.id) { alert('不能删除自己'); return }
    if (!confirm('确认删除该用户？此操作不可撤销。')) return
    setDeletingId(userId)
    try {
      await authFetch(`/api/admin/users/${userId}`, { method: 'DELETE' })
      loadUsers()
    } catch (e) {
      alert('删除失败: ' + e.message)
    } finally {
      setDeletingId(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={24} className="animate-spin text-sky-500" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="page-header page-header-divider">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-amber-50 flex items-center justify-center">
            <Users size={18} className="text-amber-600" />
          </div>
          <div>
            <h2 className="page-title">👥 用户管理</h2>
            <p className="page-subtitle">共 {total} 个用户</p>
          </div>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary text-sm py-2 px-4 flex items-center gap-1.5">
          <UserPlus size={15} /> 创建用户
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-600 text-xs">{error}</div>
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
          <input
            className="input-field text-sm py-2 pl-9 w-full"
            placeholder="搜索用户名或邮箱..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
          />
        </div>
        <select className="input-field text-sm py-2" value={roleFilter} onChange={e => { setRoleFilter(e.target.value); setPage(1) }}>
          <option value="">全部角色</option>
          {roles.map(r => <option key={r.id} value={r.name}>{ROLE_LABELS[r.name] || r.name}</option>)}
        </select>
        <select className="input-field text-sm py-2" value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1) }}>
          <option value="">全部状态</option>
          <option value="active">启用</option>
          <option value="inactive">禁用</option>
        </select>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-cloud-300/60 text-left">
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">ID</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">用户名</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">邮箱</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">角色</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">状态</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">最后登录</th>
                <th className="py-2.5 px-3 text-xs text-ink-muted font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} className="border-b border-cloud-200 hover:bg-cloud-200/50 transition-colors">
                  <td className="py-2 px-3 text-xs text-ink-muted font-mono">{u.id}</td>
                  <td className="py-2 px-3 text-ink-body flex items-center gap-1.5 font-medium">
                    {(u.role_name === 'super_admin' || u.role_name === 'admin') ? <Shield size={12} className="text-rose-500" />
                      : u.role_name === 'dept_admin' ? <Shield size={12} className="text-amber-500" />
                      : u.role_name === 'teacher' ? <Edit3 size={12} className="text-sky-500" />
                      : <User size={12} className="text-ink-muted" />}
                    {u.username}
                    {u.id === me?.id && <span className="text-[10px] text-sky-500 ml-1">(我)</span>}
                  </td>
                  <td className="py-2 px-3 text-xs text-ink-muted">{u.email}</td>
                  <td className="py-2 px-3">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-lg border ${ROLE_COLORS[u.role_name] || ROLE_COLORS.student}`}>
                      {ROLE_LABELS[u.role_name] || '只读'}
                    </span>
                  </td>
                  <td className="py-2 px-3">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-lg ${u.is_active ? 'bg-sage-50 text-sage-600 border border-sage-200' : 'bg-rose-50 text-rose-600 border border-rose-200'}`}>
                      {u.is_active ? '启用' : '禁用'}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-xs text-ink-muted">
                    {u.last_login_at ? u.last_login_at.replace('T', ' ').substring(0, 16) : '从未登录'}
                  </td>
                  <td className="py-2 px-3 flex gap-1">
                    <button className="text-ink-muted hover:text-amber-500 transition-colors" onClick={() => setEditUser(u)} title="编辑" aria-label={`编辑用户 ${u.username}`}>
                      <Edit3 size={13} aria-hidden="true"/>
                    </button>
                    {u.id !== me?.id && (
                      <button className="text-ink-muted hover:text-rose-500 transition-colors" onClick={() => handleDelete(u.id)} disabled={deletingId === u.id} title="删除" aria-label={`删除用户 ${u.username}`}>
                        {deletingId === u.id ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Trash2 size={13} aria-hidden="true"/>}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-ink-muted text-sm">暂无用户</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="px-3 pb-2">
          <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
        </div>
      </div>

      {/* Modals */}
      <CreateUserModal isOpen={showCreate} onClose={() => setShowCreate(false)} onCreated={loadUsers} roles={roles} />
      <EditUserModal user={editUser} roles={roles} isOpen={!!editUser} onClose={() => setEditUser(null)} onUpdated={loadUsers} />
    </div>
  )
}
