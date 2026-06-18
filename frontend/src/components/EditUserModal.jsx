import { useState } from 'react'
import { X, Edit3, Loader2 } from 'lucide-react'

export default function EditUserModal({ user, roles, isOpen, onClose, onUpdated }) {
  const [editForm, setEditForm] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // 初始化编辑表单
  useState(() => {
    if (user && isOpen) {
      setEditForm({
        username: user.username || '',
        email: user.email || '',
        role_id: user.role?.id || (user.is_admin ? 1 : 3),
        is_active: user.is_active !== false,
        password: '',
      })
    }
  }, [user, isOpen])

  if (!isOpen || !user) return null

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const token = JSON.parse(localStorage.getItem('raganything_auth')).token
      const body = { ...editForm }
      if (!body.password) delete body.password
      body.is_active = body.is_active ? 1 : 0
      const res = await fetch(`/api/admin/users/${user.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      onUpdated?.(data.user)
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 mx-4">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-base font-semibold text-warm-800 flex items-center gap-2">
            <Edit3 size={18} className="text-amber-500" /> 编辑用户 — {user.username}
          </h3>
          <button onClick={onClose} className="text-warm-400 hover:text-warm-600 transition-colors">
            <X size={18} />
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-600 text-xs">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-warm-600 mb-1">用户名</label>
            <input className="input-field text-sm py-2 w-full" value={editForm.username || ''}
              onChange={e => setEditForm(f => ({ ...f, username: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-warm-600 mb-1">邮箱</label>
            <input className="input-field text-sm py-2 w-full" type="email" value={editForm.email || ''}
              onChange={e => setEditForm(f => ({ ...f, email: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-warm-600 mb-1">角色</label>
            <select className="input-field text-sm py-2 w-full" value={editForm.role_id || 3}
              onChange={e => setEditForm(f => ({ ...f, role_id: Number(e.target.value) }))}>
              {(roles || []).map(r => (
                <option key={r.id} value={r.id}>{r.name} — {r.description}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-warm-600 mb-1">状态</label>
            <select className="input-field text-sm py-2 w-full" value={editForm.is_active ? '1' : '0'}
              onChange={e => setEditForm(f => ({ ...f, is_active: e.target.value === '1' }))}>
              <option value="1">启用</option>
              <option value="0">禁用</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-warm-600 mb-1">新密码（留空不修改）</label>
            <input className="input-field text-sm py-2 w-full" type="password" placeholder="留空则不修改密码"
              value={editForm.password || ''}
              onChange={e => setEditForm(f => ({ ...f, password: e.target.value }))} />
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary flex-1 py-2 text-sm">取消</button>
            <button type="submit" disabled={loading} className="btn-primary flex-1 py-2 text-sm flex items-center justify-center gap-1.5 disabled:opacity-50">
              {loading ? <Loader2 size={14} className="animate-spin" /> : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
