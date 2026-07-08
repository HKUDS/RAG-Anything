import { useState, useEffect } from 'react'
import { X, UserPlus, Loader2, Check, Circle } from 'lucide-react'

function checkPasswordStrength(pw) {
  return {
    length: pw.length >= 8,
    upper: /[A-Z]/.test(pw),
    lower: /[a-z]/.test(pw),
    digit: /[0-9]/.test(pw),
    special: /[^A-Za-z0-9]/.test(pw),
    score() {
      return [this.upper, this.lower, this.digit, this.special].filter(Boolean).length
    },
  }
}

export default function CreateUserModal({ isOpen, onClose, onCreated, roles }) {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [roleId, setRoleId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [strength, setStrength] = useState(null)

  // 从角色列表中推导默认角色 ID，默认使用“学生”
  useEffect(() => {
    if (!roles || roles.length === 0) return
    const student = roles.find(r => r.name === 'student')
    if (student) setRoleId(student.id)
  }, [roles])

  useEffect(() => { setStrength(checkPasswordStrength(password)) }, [password])

  useEffect(() => {
    if (!isOpen) return
    const handleEsc = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleEsc)
    return () => document.removeEventListener('keydown', handleEsc)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const canSubmit = username.trim().length >= 2 && email.includes('@') && strength && strength.score() >= 3

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!canSubmit) return

    setLoading(true)
    try {
      const token = JSON.parse(localStorage.getItem('raganything_auth')).token
      const res = await fetch('/api/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ username: username.trim(), email: email.trim(), password, role_id: roleId }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      onCreated?.(data.user)
      const studentRole = (roles || []).find(r => r.name === 'student')
      setUsername(''); setEmail(''); setPassword(''); setRoleId(studentRole?.id || null); setError('')
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="创建用户">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 mx-4">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-base font-semibold text-ink-primary flex items-center gap-2">
            <UserPlus size={18} className="text-sky-500" /> 创建用户
          </h3>
          <button onClick={onClose} aria-label="关闭" className="text-ink-muted hover:text-ink-body transition-colors">
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-600 text-xs">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-ink-body mb-1">用户名 *</label>
            <input className="input-field text-sm py-2 w-full" placeholder="至少 2 个字符" value={username}
              onChange={e => setUsername(e.target.value)} autoFocus />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-body mb-1">邮箱 *</label>
            <input className="input-field text-sm py-2 w-full" type="email" placeholder="user@example.com" value={email}
              onChange={e => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-body mb-1">密码 *</label>
            <input className="input-field text-sm py-2 w-full" type="password" placeholder="至少 8 位，包含 3/4 类字符" value={password}
              onChange={e => setPassword(e.target.value)} />
            {password && strength && (
              <div className="mt-2 space-y-1">
                <div className={`flex items-center gap-1.5 text-xs ${strength.length ? 'text-sage-600' : 'text-ink-muted'}`}>
                  {strength.length ? <Check size={11} /> : <Circle size={11} />} 至少 8 位
                </div>
                <div className={`flex items-center gap-1.5 text-xs ${strength.upper ? 'text-sage-600' : 'text-ink-muted'}`}>
                  {strength.upper ? <Check size={11} /> : <Circle size={11} />} 大写字母
                </div>
                <div className={`flex items-center gap-1.5 text-xs ${strength.lower ? 'text-sage-600' : 'text-ink-muted'}`}>
                  {strength.lower ? <Check size={11} /> : <Circle size={11} />} 小写字母
                </div>
                <div className={`flex items-center gap-1.5 text-xs ${strength.digit ? 'text-sage-600' : 'text-ink-muted'}`}>
                  {strength.digit ? <Check size={11} /> : <Circle size={11} />} 数字
                </div>
                <div className={`flex items-center gap-1.5 text-xs ${strength.special ? 'text-sage-600' : 'text-ink-muted'}`}>
                  {strength.special ? <Check size={11} /> : <Circle size={11} />} 特殊字符
                </div>
                <div className="text-xs text-ink-muted mt-1">
                  满足 {strength.score()} / 4 类 {strength.score() >= 3 ? '' : '（需要至少 3 类）'}
                </div>
              </div>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-body mb-1">角色</label>
            <select className="input-field text-sm py-2 w-full" value={roleId} onChange={e => setRoleId(Number(e.target.value))}>
              {(roles || []).map(r => (
                <option key={r.id} value={r.id}>{r.name} — {r.description}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary flex-1 py-2 text-sm">取消</button>
            <button type="submit" disabled={loading || !canSubmit}
              className="btn-primary flex-1 py-2 text-sm flex items-center justify-center gap-1.5 disabled:opacity-50">
              {loading ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}
              {loading ? '创建中…' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
