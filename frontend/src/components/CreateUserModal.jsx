import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, Circle, Loader2, UserPlus } from 'lucide-react'
import { UserDialog } from './UserDialog'
import UserRoleSelect from './UserRoleSelect'
import { filterAssignableRoles } from '../utils/roleOrdering'

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

export default function CreateUserModal({ isOpen, onClose, onCreated, roles, actorRole }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [roleId, setRoleId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const usernameRef = useRef(null)
  const assignableRoles = useMemo(() => filterAssignableRoles(roles, actorRole), [actorRole, roles])

  useEffect(() => {
    if (!roles?.length) return
    const studentRole = assignableRoles.find((role) => role.name === 'student')
    setRoleId((currentRoleId) => currentRoleId ?? studentRole?.id ?? assignableRoles[0]?.id ?? null)
  }, [assignableRoles, roles])

  const handleRequestClose = useCallback(() => {
    if (!loading) onClose()
  }, [loading, onClose])

  if (!isOpen) return null

  const strength = password ? checkPasswordStrength(password) : null
  const canSubmit = username.trim().length >= 2
    && Boolean(roleId)
    && strength?.score() >= 3

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    if (!canSubmit) return

    setLoading(true)
    try {
      const token = JSON.parse(localStorage.getItem('raganything_auth')).token
      const response = await fetch('/api/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          username: username.trim(),
          password,
          role_id: roleId,
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)

      onCreated?.(data.user)
      const studentRole = assignableRoles.find((role) => role.name === 'student')
      setUsername('')
      setPassword('')
      setRoleId(studentRole?.id ?? null)
      setError('')
      onClose()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <UserDialog
      isOpen={isOpen}
      title="创建用户"
      icon={<UserPlus size={18} />}
      onRequestClose={handleRequestClose}
      closeDisabled={loading}
      closeLabel="关闭创建用户弹层"
      initialFocusRef={usernameRef}
      footer={(
        <div className="flex gap-3">
          <button type="button" onClick={handleRequestClose} disabled={loading} className="btn-secondary flex-1 py-2.5 text-sm">
            取消
          </button>
          <button
            type="submit"
            form="create-user-form"
            disabled={loading || !canSubmit}
            className="btn-primary flex-1 py-2.5 text-sm flex items-center justify-center gap-1.5 disabled:opacity-50"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}
            {loading ? '创建中…' : '创建'}
          </button>
        </div>
      )}
    >
      {error && (
        <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600" role="alert">
          {error}
        </div>
      )}

      <form id="create-user-form" onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div>
          <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="create-username">用户名 *</label>
          <input
            ref={usernameRef}
            id="create-username"
            className="input-field text-sm py-2 w-full"
            placeholder="至少 2 个字符"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
            minLength={2}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-body mb-1" htmlFor="create-password">密码 *</label>
          <input
            id="create-password"
            className="input-field text-sm py-2 w-full"
            type="password"
            placeholder="至少 8 位，包含 3/4 类字符"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="new-password"
            required
          />
          {password && strength && (
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
              <div className="text-xs text-ink-muted mt-1">
                满足 {strength.score()} / 4 类 {strength.score() >= 3 ? '' : '（需要至少 3 类）'}
              </div>
            </div>
          )}
        </div>
        <UserRoleSelect id="create-role" roles={roles} value={roleId} onChange={setRoleId} disabled={loading} actorRole={actorRole} />
      </form>
    </UserDialog>
  )
}
