import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, Circle, Edit3, Loader2, Shield } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { UserDialog, UserDialogConfirmation } from './UserDialog'
import UserRoleSelect from './UserRoleSelect'

function checkPasswordStrength(password) {
  return {
    length: password.length >= 8,
    upper: /[A-Z]/.test(password),
    lower: /[a-z]/.test(password),
    digit: /[0-9]/.test(password),
    special: /[^A-Za-z0-9]/.test(password),
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
  if (form.password) {
    const strength = checkPasswordStrength(form.password)
    if (strength.score() < 3) {
      errors.password = '密码需满足至少 3/4 类字符要求'
    }
  }
  return errors
}

const FIELD_IDS = {
  username: 'edit-username',
  email: 'edit-email',
  password: 'edit-password',
}

export default function EditUserModal({ user, roles, isOpen, onClose, onUpdated }) {
  const { user: me } = useAuth()
  const [editForm, setEditForm] = useState({
    username: '',
    email: '',
    role_id: null,
    is_active: true,
    password: '',
  })
  const [initialForm, setInitialForm] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [showUnsavedWarning, setShowUnsavedWarning] = useState(false)
  const [showRoleDowngradeWarning, setShowRoleDowngradeWarning] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')

  const modalRef = useRef(null)
  const usernameRef = useRef(null)
  const closeTimerRef = useRef(null)

  useEffect(() => {
    if (!user || !isOpen) return

    const roleList = roles || []
    const userRoleName = user.role_name ?? user.role?.name
    const selectedRoleId = user.role_id
      ?? user.role?.id
      ?? roleList.find((role) => role.name === userRoleName)?.id
      ?? roleList.find((role) => role.name === 'student')?.id
      ?? null
    const form = {
      username: user.username || '',
      email: user.email || '',
      role_id: selectedRoleId,
      is_active: user.is_active !== false,
      password: '',
    }
    setEditForm(form)
    setInitialForm(form)
    setError('')
    setFieldErrors({})
    setShowUnsavedWarning(false)
    setShowRoleDowngradeWarning(false)
    setSuccessMsg('')
    setLoading(false)
  }, [isOpen, roles, user])

  useEffect(() => () => {
    if (closeTimerRef.current) window.clearTimeout(closeTimerRef.current)
  }, [])

  const hasChanges = useCallback(() => {
    if (!initialForm) return false
    return editForm.username !== initialForm.username
      || editForm.email !== initialForm.email
      || editForm.role_id !== initialForm.role_id
      || editForm.is_active !== initialForm.is_active
      || (editForm.password || '') !== (initialForm.password || '')
  }, [editForm, initialForm])

  const handleRequestClose = useCallback(() => {
    if (loading) return
    if (hasChanges() && !successMsg) {
      setShowUnsavedWarning(true)
      return
    }
    onClose()
  }, [hasChanges, loading, onClose, successMsg])

  const confirmDiscard = () => {
    setShowUnsavedWarning(false)
    onClose()
  }

  const clearFieldError = (field) => {
    if (!fieldErrors[field]) return
    setFieldErrors((previous) => {
      const next = { ...previous }
      delete next[field]
      return next
    })
  }

  if (!isOpen || !user) return null

  const isEditingSelf = me?.id === user.id
  const userRoleName = user.role_name ?? user.role?.name
  const userRoleId = user.role_id
    ?? user.role?.id
    ?? roles?.find((role) => role.name === userRoleName)?.id
  const isAdminSelf = isEditingSelf && userRoleName === 'super_admin'
  const superAdminRoleId = userRoleId ?? roles?.find((role) => role.name === 'super_admin')?.id
  const isSelfDemotion = isAdminSelf && editForm.role_id !== superAdminRoleId
  const strength = editForm.password ? checkPasswordStrength(editForm.password) : null
  const hasConfirmationOpen = showUnsavedWarning || showRoleDowngradeWarning

  const saveUser = async () => {
    if (loading) return

    setLoading(true)
    try {
      const token = JSON.parse(localStorage.getItem('raganything_auth')).token
      const body = { ...editForm }
      if (!body.password) delete body.password
      body.is_active = body.is_active ? 1 : 0

      const response = await fetch(`/api/admin/users/${user.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)

      const savedForm = { ...editForm, password: '' }
      setEditForm(savedForm)
      setInitialForm(savedForm)
      setSuccessMsg(isEditingSelf ? '个人信息已更新' : `用户 ${editForm.username} 已更新`)

      closeTimerRef.current = window.setTimeout(() => {
        onUpdated?.(data.user)
        onClose()
      }, 1200)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (event) => {
    event.preventDefault()
    setError('')
    setSuccessMsg('')

    const errors = validateEditForm(editForm)
    setFieldErrors(errors)
    const firstError = Object.keys(errors)[0]
    if (firstError) {
      modalRef.current?.querySelector(`#${FIELD_IDS[firstError]}`)?.focus()
      return
    }

    if (isSelfDemotion) {
      setShowRoleDowngradeWarning(true)
      return
    }

    saveUser()
  }

  const confirmRoleDowngrade = () => {
    setShowRoleDowngradeWarning(false)
    saveUser()
  }

  return (
    <>
      <UserDialog
        isOpen={isOpen}
        title={`编辑用户：${user.username}`}
        icon={<Edit3 size={18} />}
        onRequestClose={handleRequestClose}
        closeDisabled={loading}
        closeLabel="关闭编辑用户弹层"
        dialogRef={modalRef}
        initialFocusRef={usernameRef}
        trapFocus={!hasConfirmationOpen}
        ariaHidden={hasConfirmationOpen}
        footer={(
          <div className="flex gap-3">
            <button type="button" onClick={handleRequestClose} disabled={loading} className="btn-secondary flex-1 py-2.5 text-sm">
              取消
            </button>
            <button
              type="submit"
              form="edit-user-form"
              disabled={loading}
              className="btn-primary flex-1 py-2.5 text-sm flex items-center justify-center gap-1.5 disabled:opacity-50"
            >
              {loading && <Loader2 size={14} className="animate-spin" />}
              {loading ? '保存中…' : '保存'}
            </button>
          </div>
        )}
      >
        {successMsg && (
          <div className="mb-4 flex items-center gap-2 rounded-xl border border-sage-200 bg-sage-50 p-3 text-xs font-medium text-sage-700" role="status" aria-live="polite">
            <Check size={14} className="text-sage-500" aria-hidden="true" /> {successMsg}
          </div>
        )}

        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600" role="alert">
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-rose-400" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        {isEditingSelf && (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
            <Shield size={14} className="mt-0.5 shrink-0 text-amber-500" aria-hidden="true" />
            <div>
              <p className="font-medium">你正在编辑自己的账户</p>
              <p className="mt-0.5 text-amber-600">
                {isAdminSelf
                  ? '降低角色会立即影响管理权限，之后需由其他超级管理员恢复。'
                  : '部分更改会在下次登录时生效。'}
              </p>
            </div>
          </div>
        )}

        <form id="edit-user-form" onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="edit-username">用户名</label>
            <input
              ref={usernameRef}
              id="edit-username"
              className={`input-field text-sm py-2 w-full ${fieldErrors.username ? 'border-rose-300 bg-rose-50/30' : ''}`}
              value={editForm.username}
              onChange={(event) => {
                setEditForm((form) => ({ ...form, username: event.target.value }))
                clearFieldError('username')
              }}
              placeholder="至少 2 个字符"
              autoComplete="username"
              required
              minLength={2}
              aria-invalid={Boolean(fieldErrors.username)}
              aria-describedby={fieldErrors.username ? 'edit-username-error' : undefined}
            />
            {fieldErrors.username && <p id="edit-username-error" className="text-2xs text-rose-500 mt-1">{fieldErrors.username}</p>}
          </div>

          <div>
            <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="edit-email">邮箱</label>
            <input
              id="edit-email"
              className={`input-field text-sm py-2 w-full ${fieldErrors.email ? 'border-rose-300 bg-rose-50/30' : ''}`}
              type="email"
              value={editForm.email}
              onChange={(event) => {
                setEditForm((form) => ({ ...form, email: event.target.value }))
                clearFieldError('email')
              }}
              placeholder="user@example.com"
              autoComplete="email"
              aria-invalid={Boolean(fieldErrors.email)}
              aria-describedby={fieldErrors.email ? 'edit-email-error' : undefined}
            />
            {fieldErrors.email && <p id="edit-email-error" className="text-2xs text-rose-500 mt-1">{fieldErrors.email}</p>}
          </div>

          <UserRoleSelect
            id="edit-role"
            roles={roles}
            value={editForm.role_id}
            onChange={(roleId) => setEditForm((form) => ({ ...form, role_id: roleId }))}
            disabled={loading}
            cautionLabel={isAdminSelf ? '谨慎修改' : undefined}
          />

          <div>
            <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="edit-status">状态</label>
            <select
              id="edit-status"
              className="input-field text-sm py-2 w-full"
              value={editForm.is_active ? '1' : '0'}
              onChange={(event) => setEditForm((form) => ({ ...form, is_active: event.target.value === '1' }))}
              disabled={loading}
            >
              <option value="1">启用</option>
              <option value="0">禁用</option>
            </select>
            {isEditingSelf && !editForm.is_active && (
              <p className="text-2xs text-rose-500 mt-1">注意：禁用自己的账户将导致无法登录。</p>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="edit-password">新密码（留空不修改）</label>
            <input
              id="edit-password"
              className={`input-field text-sm py-2 w-full ${fieldErrors.password ? 'border-rose-300 bg-rose-50/30' : ''}`}
              type="password"
              placeholder="留空则不修改密码"
              value={editForm.password}
              onChange={(event) => {
                setEditForm((form) => ({ ...form, password: event.target.value }))
                clearFieldError('password')
              }}
              autoComplete="new-password"
              aria-invalid={Boolean(fieldErrors.password)}
              aria-describedby={fieldErrors.password ? 'edit-password-error' : undefined}
            />
            {fieldErrors.password && <p id="edit-password-error" className="text-2xs text-rose-500 mt-1">{fieldErrors.password}</p>}

            {strength && (
              <div className="mt-2 space-y-1" aria-live="polite">
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
                <div className={`mt-1 text-xs ${strength.score() >= 3 ? 'text-sage-600' : 'text-rose-500'}`}>
                  满足 {strength.score()} / 4 类 {strength.score() >= 3 ? '' : '（需要至少 3 类）'}
                </div>
              </div>
            )}
          </div>
        </form>
      </UserDialog>

      <UserDialogConfirmation
        isOpen={showUnsavedWarning}
        title="放弃未保存的更改？"
        description="关闭后，本次编辑内容将不会保存。"
        icon={<AlertTriangle size={18} />}
        cancelLabel="继续编辑"
        confirmLabel="放弃更改"
        onCancel={() => setShowUnsavedWarning(false)}
        onConfirm={confirmDiscard}
        danger
      />

      <UserDialogConfirmation
        isOpen={showRoleDowngradeWarning}
        title="确认降低自身权限？"
        description="降低后将失去用户管理和审计等管理权限，需由其他超级管理员恢复。"
        icon={<AlertTriangle size={18} />}
        cancelLabel="继续编辑"
        confirmLabel="确认降级"
        onCancel={() => setShowRoleDowngradeWarning(false)}
        onConfirm={confirmRoleDowngrade}
        danger
      />
    </>
  )
}
