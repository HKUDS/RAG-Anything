import { useState, useEffect, useCallback } from 'react'
import { Trash2, Edit3, X, Check, Loader2, Shield, User, Users } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

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

export default function AdminUsersPage() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState({})
  const [deletingId, setDeletingId] = useState(null)

  const loadUsers = useCallback(async () => {
    try {
      const data = await authFetch('/api/admin/users')
      setUsers(data.users || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadUsers() }, [loadUsers])

  const startEdit = (u) => {
    setEditingId(u.id)
    setEditForm({ username: u.username, email: u.email, is_admin: !!u.is_admin, is_active: !!u.is_active, password: '' })
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditForm({})
  }

  const saveEdit = async (userId) => {
    try {
      const body = { ...editForm }
      if (!body.password) delete body.password
      await authFetch(`/api/admin/users/${userId}`, { method: 'PUT', body: JSON.stringify(body) })
      cancelEdit()
      loadUsers()
    } catch (e) {
      alert('保存失败: ' + e.message)
    }
  }

  const handleDelete = async (userId) => {
    if (userId === me?.id) {
      alert('不能删除自己')
      return
    }
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
        <Loader2 size={24} className="animate-spin text-neon-400" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Users size={20} className="text-neon-400" />
        <div>
          <h2 className="text-lg font-bold text-slate-200">用户管理</h2>
          <p className="text-xs text-slate-500">共 {users.length} 个用户</p>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">{error}</div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50 text-left">
              <th className="py-2 px-3 text-xs text-slate-500 font-medium">ID</th>
              <th className="py-2 px-3 text-xs text-slate-500 font-medium">用户名</th>
              <th className="py-2 px-3 text-xs text-slate-500 font-medium">邮箱</th>
              <th className="py-2 px-3 text-xs text-slate-500 font-medium">角色</th>
              <th className="py-2 px-3 text-xs text-slate-500 font-medium">状态</th>
              <th className="py-2 px-3 text-xs text-slate-500 font-medium">创建时间</th>
              <th className="py-2 px-3 text-xs text-slate-500 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                {editingId === u.id ? (
                  <>
                    <td className="py-2 px-3 text-xs text-slate-400 font-mono">{u.id}</td>
                    <td className="py-2 px-3">
                      <input className="input-field text-xs py-1 w-full" value={editForm.username || ''}
                        onChange={e => setEditForm(f => ({ ...f, username: e.target.value }))} />
                    </td>
                    <td className="py-2 px-3">
                      <input className="input-field text-xs py-1 w-full" value={editForm.email || ''}
                        onChange={e => setEditForm(f => ({ ...f, email: e.target.value }))} />
                    </td>
                    <td className="py-2 px-3">
                      <select className="input-field text-xs py-1" value={editForm.is_admin ? '1' : '0'}
                        onChange={e => setEditForm(f => ({ ...f, is_admin: e.target.value === '1' }))}>
                        <option value="0">用户</option>
                        <option value="1">管理员</option>
                      </select>
                    </td>
                    <td className="py-2 px-3">
                      <select className="input-field text-xs py-1" value={editForm.is_active ? '1' : '0'}
                        onChange={e => setEditForm(f => ({ ...f, is_active: e.target.value === '1' }))}>
                        <option value="1">启用</option>
                        <option value="0">禁用</option>
                      </select>
                    </td>
                    <td className="py-2 px-3 text-xs text-slate-500">{u.created_at?.split('T')[0]}</td>
                    <td className="py-2 px-3 flex gap-1">
                      <button className="text-emerald-400 hover:text-emerald-300" onClick={() => saveEdit(u.id)} title="保存"><Check size={14}/></button>
                      <button className="text-slate-500 hover:text-slate-300" onClick={cancelEdit} title="取消"><X size={14}/></button>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="py-2 px-3 text-xs text-slate-500 font-mono">{u.id}</td>
                    <td className="py-2 px-3 text-slate-300 flex items-center gap-1.5">
                      {u.is_admin ? <Shield size={12} className="text-amber-400" /> : <User size={12} className="text-slate-500" />}
                      {u.username}
                      {u.id === me?.id && <span className="text-[10px] text-neon-500 ml-1">(我)</span>}
                    </td>
                    <td className="py-2 px-3 text-xs text-slate-400">{u.email}</td>
                    <td className="py-2 px-3">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${u.is_admin ? 'bg-amber-500/10 text-amber-400' : 'bg-slate-700/50 text-slate-400'}`}>
                        {u.is_admin ? '管理员' : '用户'}
                      </span>
                    </td>
                    <td className="py-2 px-3">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${u.is_active ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                        {u.is_active ? '启用' : '禁用'}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-xs text-slate-500">{u.created_at?.split('T')[0]}</td>
                    <td className="py-2 px-3 flex gap-1">
                      <button className="text-slate-500 hover:text-neon-400" onClick={() => startEdit(u)} title="编辑"><Edit3 size={13}/></button>
                      {u.id !== me?.id && (
                        <button className="text-slate-500 hover:text-red-400" onClick={() => handleDelete(u.id)} disabled={deletingId === u.id} title="删除">
                          {deletingId === u.id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13}/>}
                        </button>
                      )}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
