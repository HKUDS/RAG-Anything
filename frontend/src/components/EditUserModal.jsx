import { useState, useEffect, useRef, useCallback } from 'react'
import { X, Edit3, Loader2, Check, Circle, AlertTriangle, Shield } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

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

function validateEditForm(form) {
  const errors = {}
  if (!form.username || form.username.trim().length < 2) {
    errors.username = '用户名至少需要 2 个字符'
  }
  if (form.email && !form.email.includes('@')) {
    errors.email = '请输入有效的邮箱地址'
  }
  if (form.password && form.password.length > 0) {
    const strength = checkPasswordStrength(form.password)
    if (strength.score() < 3) {
      errors.password = '密码需满足至少 3/4 类字符要求'
    }
  }
  return errors
}

export default function EditUserModal({ user, roles, isOpen, onClose, onUpdated }) {
  const { user: me } = useAuth()
  const [editForm, setEditForm] = useState({
    username: '',
    email: '',
    role_id: 3,
    is_active: true,
    password: '',
  })
  const [initialForm, setInitialForm] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [strength, setStrength] = useState(null)
  const [showUnsavedWarning, setShowUnsavedWarning] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')

  const modalRef = useRef(null)
  const closeBtnRef = useRef(null)

  // 初始化编辑表单 (正确使用 useEffect，修复 useState 误用 bug)
  useEffect(() => {
    if (user && isOpen) {
      const form = {
        username: user.username || '',
        email: user.email || '',
        role_id: user.role?.id || (user.is_admin
          ? ((roles || []).find(r => r.name === 'super_admin')?.id || (roles || []).find(r => r.name === 'admin')?.id)
          : ((roles || []).find(r => r.name === 'student')?.id)),
        is_active: user.is_active !== false,
        password: '',
      }
      setEditForm(form)
      setInitialForm(form)
      setError('')
      setFieldErrors({})
      setShowUnsavedWarning(false)
      setSuccessMsg('')
      setStrength(null)
    }
  }, [user, isOpen])

  // 密码强度实时检测
  useEffect(() => {
    const pw = editForm.password || ''
    setStrength(pw.length > 0 ? checkPasswordStrength(pw) : null)
  }, [editForm.password])

  // 判断表单是否有未保存的更改
  const hasChanges = useCallback(() => {
    if (!initialForm) return false
    return (
      editForm.username !== initialForm.username ||
      editForm.email !== initialForm.email ||
      editForm.role_id !== initialForm.role_id ||
      editForm.is_active !== initialForm.is_active ||
      (editForm.password || '') !== (initialForm.password || '')
    )
  }, [editForm, initialForm])

  // 关闭弹窗处理（带未保存确认）
  const handleClose = useCallback(() => {
    if (hasChanges() && !successMsg) {
      setShowUnsavedWarning(true)
    } else {
      onClose()
    }
  }, [hasChanges, onClose, successMsg])

  // 确认放弃更改
  const confirmDiscard = () => {
    setShowUnsavedWarning(false)
    onClose()
  }

  // ESC 关闭
  useEffect(() => {
    if (!isOpen) return
    const handleEsc = (e) => { if (e.key === 'Escape') handleClose() }
    document.addEventListener('keydown', handleEsc)
    return () => document.removeEventListener('keydown', handleEsc)
  }, [isOpen, handleClose])

  // 聚焦管理：打开弹窗时聚焦第一个输入框
  useEffect(() => {
    if (isOpen && modalRef.current) {
      const firstInput = modalRef.current.querySelector('input, select')
      if (firstInput) firstInput.focus()
    }
  }, [isOpen])

  // 点击背景关闭
  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) handleClose()
  }

  if (!isOpen || !user) return null

  const isEditingSelf = me?.id === user.id
  const adminRoleIds = (roles || []).filter(r => r.name === 'super_admin' || r.name === 'admin').map(r => r.id)
  const isAdminSelf = isEditingSelf && (user.role?.name === 'super_admin' || user.role?.name === 'admin' || user.is_admin)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSuccessMsg('')

    // 表单验证
    const errors = validateEditForm(editForm)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) {
      // 聚焦第一个有错误的字段
      const firstErrorField = modalRef.current?.querySelector('[data-error]')
      if (firstErrorField) firstErrorField.focus()
      return
    }

    // 管理员修改自身角色为降级时给出额外确认
    if (isAdminSelf && !adminRoleIds.includes(editForm.role_id)) {
      if (!confirm('⚠️ 你正在将自己的角色从管理员降级！\n\n降级后将失去管理权限（用户管理、审计日志等），且无法自行恢复。\n\n确认继续？')) {
        return
      }
    }

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

      // 显示成功反馈
      setSuccessMsg(isEditingSelf ? '✅ 个人信息已更新' : `✅ 用户 ${editForm.username} 已更新`)
      setInitialForm({ ...editForm, password: '' }) // 更新基准，防止关闭时再次提示

      // 延迟关闭，让用户看到成功消息
      setTimeout(() => {
        onUpdated?.(data.user)
        onClose()
      }, 1200)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const clearFieldError = (field) => {
    if (fieldErrors[field]) {
      setFieldErrors(prev => { const next = { ...prev }; delete next[field]; return next })
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-label={`编辑用户 — ${user.username}`}
      ref={modalRef}
    >
      {/* 主卡片 */}
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 mx-4" onClick={e => e.stopPropagation()}>
        {/* 头部 */}
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-base font-semibold text-ink-primary flex items-center gap-2">
            <Edit3 size={18} className="text-amber-500" aria-hidden="true" />
            编辑用户 — {user.username}
            {isEditingSelf && (
              <span className="text-[10px] font-normal text-sky-500 bg-sky-50 px-1.5 py-0.5 rounded-lg border border-coral-200 ml-1">
                自己
              </span>
            )}
          </h3>
          <button
            ref={closeBtnRef}
            onClick={handleClose}
            className="text-ink-muted hover:text-ink-body transition-colors p-1 rounded-lg hover:bg-cloud-200"
            aria-label="关闭编辑弹窗"
            disabled={loading}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        {/* 成功消息 */}
        {successMsg && (
          <div className="mb-4 p-3 rounded-xl bg-sage-50 border border-sage-200 text-sage-700 text-xs font-medium flex items-center gap-2">
            <Check size={14} className="text-sage-500" /> {successMsg}
          </div>
        )}

        {/* 错误消息 */}
        {error && (
          <div className="mb-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-600 text-xs flex items-start gap-2">
            <AlertTriangle size={14} className="text-rose-400 flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* 自编辑提示 */}
        {isEditingSelf && (
          <div className="mb-4 p-3 rounded-xl bg-amber-50 border border-amber-200 text-amber-700 text-xs flex items-start gap-2">
            <Shield size={14} className="text-amber-500 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">你正在编辑自己的账户</p>
              <p className="mt-0.5 text-amber-600">
                {isAdminSelf
                  ? '修改角色将立即影响你的管理权限。降级为普通角色后需要其他管理员恢复。'
                  : '某些更改将在下次登录时生效。'}
              </p>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          {/* 用户名 */}
          <div>
            <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="edit-username">
              用户名
            </label>
            <input
              id="edit-username"
              className={`input-field text-sm py-2 w-full ${fieldErrors.username ? 'border-rose-300 bg-rose-50/30' : ''}`}
              value={editForm.username || ''}
              data-error={fieldErrors.username ? 'true' : undefined}
              onChange={e => {
                setEditForm(f => ({ ...f, username: e.target.value }))
                clearFieldError('username')
              }}
              placeholder="至少 2 个字符"
              required
              minLength={2}
            />
            {fieldErrors.username && (
              <p className="text-[11px] text-rose-500 mt-1">{fieldErrors.username}</p>
            )}
          </div>

          {/* 邮箱 */}
          <div>
            <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="edit-email">
              邮箱
            </label>
            <input
              id="edit-email"
              className={`input-field text-sm py-2 w-full ${fieldErrors.email ? 'border-rose-300 bg-rose-50/30' : ''}`}
              type="email"
              value={editForm.email || ''}
              data-error={fieldErrors.email ? 'true' : undefined}
              onChange={e => {
                setEditForm(f => ({ ...f, email: e.target.value }))
                clearFieldError('email')
              }}
              placeholder="user@example.com"
            />
            {fieldErrors.email && (
              <p className="text-[11px] text-rose-500 mt-1">{fieldErrors.email}</p>
            )}
          </div>

          {/* 角色 */}
          <div>
            <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="edit-role">
              角色
              {isAdminSelf && (
                <span className="ml-2 text-[10px] text-amber-500 font-normal">⚠ 谨慎更改</span>
              )}
            </label>
            <select
              id="edit-role"
              className="input-field text-sm py-2 w-full"
              value={editForm.role_id || ''}
              onChange={e => setEditForm(f => ({ ...f, role_id: Number(e.target.value) }))}
            >
              {(roles || []).map(r => {
                const ROLE_LABEL = {
                  super_admin: '超级管理员', admin: '管理员', dept_admin: '系部管理员',
                  teacher: '主讲教师', assistant: '助理教师', student: '学生',
                }
                return (
                <option key={r.id} value={r.id}>
                  {ROLE_LABEL[r.name] || r.name}
                  {r.description ? ` — ${r.description}` : ''}
                  {r.id === user.role?.id ? ' (当前)' : ''}
                </option>
                )
              })}
            </select>
          </div>

          {/* 状态 */}
          <div>
            <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="edit-status">
              状态
            </label>
            <select
              id="edit-status"
              className="input-field text-sm py-2 w-full"
              value={editForm.is_active ? '1' : '0'}
              onChange={e => setEditForm(f => ({ ...f, is_active: e.target.value === '1' }))}
            >
              <option value="1">✅ 启用</option>
              <option value="0">🚫 禁用</option>
            </select>
            {isEditingSelf && !editForm.is_active && (
              <p className="text-[11px] text-rose-500 mt-1">⚠️ 禁用自己将导致无法登录</p>
            )}
          </div>

          {/* 新密码 */}
          <div>
            <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="edit-password">
              新密码（留空不修改）
            </label>
            <input
              id="edit-password"
              className={`input-field text-sm py-2 w-full ${fieldErrors.password ? 'border-rose-300 bg-rose-50/30' : ''}`}
              type="password"
              placeholder="留空则不修改密码"
              value={editForm.password || ''}
              data-error={fieldErrors.password ? 'true' : undefined}
              onChange={e => {
                setEditForm(f => ({ ...f, password: e.target.value }))
                clearFieldError('password')
              }}
              autoComplete="new-password"
            />
            {fieldErrors.password && (
              <p className="text-[11px] text-rose-500 mt-1">{fieldErrors.password}</p>
            )}

            {/* 密码强度指示器（与 CreateUserModal 保持一致） */}
            {strength && (
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
                <div className={`text-xs mt-1 ${strength.score() >= 3 ? 'text-sage-600' : 'text-rose-500'}`}>
                  满足 {strength.score()} / 4 类 {strength.score() >= 3 ? '✅' : '（需要至少 3 类）'}
                </div>
              </div>
            )}
          </div>

          {/* 操作按钮 */}
          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={handleClose}
              className="btn-secondary flex-1 py-2 text-sm"
              disabled={loading}
            >
              取消
            </button>
            <button
              type="submit"
              disabled={loading}
              className="btn-primary flex-1 py-2 text-sm flex items-center justify-center gap-1.5 disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  保存中…
                </>
              ) : (
                '保存'
              )}
            </button>
          </div>
        </form>
      </div>

      {/* 未保存更改警告弹窗 */}
      {showUnsavedWarning && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm"
          onClick={() => setShowUnsavedWarning(false)}
          role="dialog"
          aria-modal="true"
          aria-label="未保存的更改"
        >
          <div
            className="bg-white rounded-2xl shadow-xl w-full max-w-sm p-6 mx-4"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center">
                <AlertTriangle size={18} className="text-amber-500" />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-ink-primary">未保存的更改</h4>
                <p className="text-xs text-ink-muted mt-0.5">你有未保存的更改，确定要放弃吗？</p>
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setShowUnsavedWarning(false)}
                className="btn-secondary flex-1 py-2 text-sm"
              >
                继续编辑
              </button>
              <button
                onClick={confirmDiscard}
                className="flex-1 py-2 text-sm rounded-xl bg-rose-50 text-rose-600 hover:bg-rose-100 transition-colors font-medium"
              >
                放弃更改
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
