import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Trash2, Edit3, Loader2, Shield, User, Users, Search, UserPlus, X } from 'lucide-react'
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

const PERMISSION_LABELS = {
  'users:read': '用户查看',
  'users:write': '用户编辑',
  'users:delete': '用户删除',
  'kb:read': '知识库查看',
  'kb:write': '知识库编辑',
  'kb:delete': '知识库删除',
  'agent:read': '智能体查看',
  'agent:write': '智能体编辑',
  'agent:delete': '智能体删除',
  'settings:read': '设置查看',
  'settings:write': '设置编辑',
  'audit:read': '审计查看',
  'monitor:read': '监控查看',
  'analytics:read': '分析查看',
  'workflow:read': '工作流查看',
  'workflow:write': '工作流编辑',
  'graph:read': '图谱查看',
  'graph:write': '图谱编辑',
  'autorepair:read': '汽修查看',
  'autorepair:write': '汽修编辑',
}

const ROLE_DETAILS_COPY = {
  title: '角色权限',
  helper: '停留可预览，点击可固定查看该身份的权限边界与说明。',
  unavailable: '权限信息暂不可用，请稍后重试。',
  emptyDescription: '暂无角色说明',
  emptyPermissions: '当前角色暂未配置细分权限。',
}

function getRolePopoverPosition(anchorRect) {
  if (!anchorRect) return { top: 80, left: 16, width: 320 }

  const chipRect = anchorRect.chipRect || anchorRect
  const triggerRect = anchorRect.triggerRect || chipRect
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const isCompact = viewportWidth < 640
  const desktopPopoverWidth = 336
  const popoverWidth = isCompact
    ? Math.min(viewportWidth - 24, 320)
    : desktopPopoverWidth
  const estimatedHeight = isCompact ? 300 : 280
  const gutter = 12
  const compactGap = 4
  const desktopLiftY = 86
  const desktopGapX = 8

  if (isCompact) {
    const left = Math.min(Math.max(gutter, triggerRect.left), viewportWidth - popoverWidth - gutter)

    const preferBelowTop = triggerRect.bottom + compactGap
    const preferAboveTop = triggerRect.top - estimatedHeight - compactGap
    const top = preferBelowTop + estimatedHeight <= viewportHeight - gutter
      ? preferBelowTop
      : Math.max(gutter, preferAboveTop)
    return { mode: 'fixed', top, left, width: popoverWidth }
  }

  const preferredLeft = triggerRect.right + desktopGapX
  const left = Math.min(preferredLeft, viewportWidth - popoverWidth - gutter)
  const preferredTop = chipRect.top - desktopLiftY
  const top = Math.max(gutter, Math.min(preferredTop, viewportHeight - estimatedHeight - gutter))

  return { mode: 'fixed', top, left, width: popoverWidth }
}

function getRoleAnchorRect(trigger) {
  const triggerRect = trigger?.getBoundingClientRect?.()
  if (!triggerRect) return null

  const roleChip = trigger?.querySelector?.('[data-role-chip="true"]')
  const roleCell = trigger?.closest?.('td')
  const statusCell = roleCell?.nextElementSibling

  return {
    triggerRect,
    chipRect: roleChip?.getBoundingClientRect?.() || triggerRect,
    cellRect: roleCell?.getBoundingClientRect?.() || triggerRect,
    statusCellRect: statusCell?.getBoundingClientRect?.() || null,
  }
}

function RolePermissionPopover({ role, anchorRect, pinned, onClose, onMouseEnter, onMouseLeave, popoverRef }) {
  const closeButtonRef = useRef(null)

  useEffect(() => {
    if (!role || !pinned) return

    const handleEsc = (event) => {
      if (event.key === 'Escape') onClose()
    }

    document.addEventListener('keydown', handleEsc)

    return () => {
      document.removeEventListener('keydown', handleEsc)
    }
  }, [role, pinned, onClose])

  if (!role) return null

  const roleLabel = ROLE_LABELS[role.name] || role.name || '只读'
  const permissions = role.permissions || []
  const hasPermissionDetails = role.detailsAvailable && permissions.length > 0
  const position = getRolePopoverPosition(anchorRect)
  const popover = (
    <div
      ref={popoverRef}
      id="role-permission-panel"
      className="fixed z-50"
      style={{ top: position.top, left: position.left, width: position.width }}
      role="dialog"
      aria-modal="false"
      aria-labelledby="role-permission-title"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div
        className="overflow-hidden rounded-2xl border border-cloud-300 bg-white shadow-[0_18px_48px_rgba(38,72,96,0.16)]"
      >
        <div className="border-b border-cloud-300/60 bg-cloud-100/85 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-2xs font-medium text-ink-muted">{ROLE_DETAILS_COPY.title}</p>
              <h3 id="role-permission-title" className="mt-1 text-sm font-semibold text-ink-primary">
                {roleLabel}
              </h3>
            </div>
            {pinned && (
              <button
                ref={closeButtonRef}
                type="button"
                onClick={onClose}
                className="rounded-xl p-1.5 text-ink-muted transition-colors hover:bg-white hover:text-ink-body"
                aria-label={`关闭${roleLabel}权限详情`}
              >
                <X size={14} aria-hidden="true" />
              </button>
            )}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={`rounded-lg border px-2 py-1 text-2xs ${ROLE_COLORS[role.name] || ROLE_COLORS.student}`}>
              {roleLabel}
            </span>
            <span className="text-2xs text-ink-muted">
              {role.detailsAvailable ? `${permissions.length} 项权限` : ROLE_DETAILS_COPY.unavailable}
            </span>
          </div>

          <p className="mt-2 text-xs leading-5 text-ink-muted">
            {role.description || ROLE_DETAILS_COPY.emptyDescription}
          </p>
        </div>

        <div className="max-h-[280px] space-y-3 overflow-y-auto px-4 py-3">
          {hasPermissionDetails ? (
            <div className="grid grid-cols-3 gap-2">
              {permissions.map(permission => (
                <span
                  key={permission}
                  className="flex min-w-0 items-center justify-center rounded-lg border border-cloud-200 bg-white px-2 py-1 text-center text-xs leading-5 text-ink-body"
                >
                  {PERMISSION_LABELS[permission] || permission}
                </span>
              ))}
            </div>
          ) : (
            <div className="rounded-2xl border border-dashed border-cloud-300 bg-white p-4 text-sm text-ink-muted">
              {role.detailsAvailable ? ROLE_DETAILS_COPY.emptyPermissions : ROLE_DETAILS_COPY.unavailable}
            </div>
          )}
        </div>
      </div>
    </div>
  )

  if (typeof document === 'undefined') return popover
  return createPortal(popover, document.body)
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
  const [rolePopover, setRolePopover] = useState(null)

  // 弹窗
  const [showCreate, setShowCreate] = useState(false)
  const [editUser, setEditUser] = useState(null)

  const lastRoleTriggerRef = useRef(null)
  const anchorElementRef = useRef(null)
  const popoverRef = useRef(null)
  const hoverCloseTimerRef = useRef(null)

  const roleMap = roles.reduce((map, role) => {
    map[role.name] = role
    return map
  }, {})
  const resolveRoleDetails = (roleName) => {
    if (!roleName) {
      return {
        name: '',
        description: ROLE_DETAILS_COPY.unavailable,
        permissions: [],
        detailsAvailable: false,
      }
    }

    if (roleMap[roleName]) {
      return {
        ...roleMap[roleName],
        detailsAvailable: true,
      }
    }

    return {
      name: roleName,
      description: roles.length > 0 ? ROLE_DETAILS_COPY.emptyDescription : ROLE_DETAILS_COPY.unavailable,
      permissions: [],
      detailsAvailable: roles.length > 0,
    }
  }

  const activeRole = rolePopover?.roleName ? resolveRoleDetails(rolePopover.roleName) : null

  const clearHoverCloseTimer = useCallback(() => {
    if (hoverCloseTimerRef.current) {
      window.clearTimeout(hoverCloseTimerRef.current)
      hoverCloseTimerRef.current = null
    }
  }, [])

  const closeRoleDetails = useCallback((restoreFocus = true) => {
    clearHoverCloseTimer()
    anchorElementRef.current = null
    setRolePopover(null)
    if (restoreFocus) {
      window.requestAnimationFrame(() => lastRoleTriggerRef.current?.focus())
    }
  }, [clearHoverCloseTimer])

  const scheduleHoverClose = useCallback(() => {
    clearHoverCloseTimer()
    hoverCloseTimerRef.current = window.setTimeout(() => {
      setRolePopover((current) => (current?.pinned ? current : null))
    }, 120)
  }, [clearHoverCloseTimer])

  const syncRolePopover = useCallback((roleName, sourceId, trigger, pinned) => {
    if (!roleName) return
    anchorElementRef.current = trigger
    setRolePopover({
      sourceId,
      roleName,
      pinned,
      anchorRect: getRoleAnchorRect(trigger),
    })
  }, [])

  const previewRoleDetails = useCallback((roleName, sourceId, trigger) => {
    clearHoverCloseTimer()
    setRolePopover((current) => {
      if (current?.pinned && current.sourceId !== sourceId) return current
      anchorElementRef.current = trigger
      return {
        sourceId,
        roleName,
        pinned: current?.pinned && current.sourceId === sourceId,
        anchorRect: getRoleAnchorRect(trigger),
      }
    })
  }, [clearHoverCloseTimer])

  const openRoleDetails = useCallback((roleName, sourceId, trigger) => {
    clearHoverCloseTimer()
    if (!roleName) return

    if (rolePopover?.pinned && rolePopover.sourceId === sourceId) {
      closeRoleDetails()
      return
    }

    syncRolePopover(roleName, sourceId, trigger, true)
    lastRoleTriggerRef.current = trigger
  }, [clearHoverCloseTimer, closeRoleDetails, rolePopover, syncRolePopover])

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
    } catch (_) {
      setRoles([])
    }
  }, [])

  useEffect(() => { loadUsers() }, [loadUsers])
  useEffect(() => { loadRoles() }, [loadRoles])

  useEffect(() => {
    setRolePopover(null)
  }, [page, search, roleFilter, statusFilter])

  useEffect(() => () => clearHoverCloseTimer(), [clearHoverCloseTimer])

  useEffect(() => {
    if (!rolePopover || !anchorElementRef.current) return

    const updatePosition = () => {
      if (!anchorElementRef.current?.isConnected) {
        setRolePopover(null)
        return
      }
      setRolePopover((current) => (current ? {
        ...current,
        anchorRect: getRoleAnchorRect(anchorElementRef.current),
      } : current))
    }

    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)

    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [rolePopover])

  useEffect(() => {
    if (!rolePopover?.pinned) return

    const handlePointerDown = (event) => {
      const target = event.target
      if (popoverRef.current?.contains(target) || anchorElementRef.current?.contains(target)) return
      closeRoleDetails(false)
    }

    document.addEventListener('pointerdown', handlePointerDown)
    return () => document.removeEventListener('pointerdown', handlePointerDown)
  }, [rolePopover, closeRoleDetails])

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
      <div className="flex h-full items-center justify-center">
        <Loader2 size={24} className="animate-spin text-sky-500" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* 头部 */}
      <div className="page-header page-header-divider">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-50">
            <Users size={18} className="text-amber-600" />
          </div>
          <div>
            <h2 className="page-title">用户管理</h2>
            <p className="page-subtitle">共 {total} 个用户</p>
          </div>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary flex items-center gap-1.5 px-4 py-2 text-sm">
          <UserPlus size={15} /> 创建用户
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600">{error}</div>
      )}

      {/* 工具栏 */}
      <div className="grid gap-3 lg:grid-cols-[minmax(240px,1fr)_auto] lg:items-center">
        <div className="relative w-full max-w-xl">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
          <input
            className="input-field w-full py-2 pl-9 text-sm"
            placeholder="搜索用户名或邮箱..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:min-w-[396px]">
          <select
            className="select-field w-full py-2 text-sm"
            value={roleFilter}
            onChange={e => { setRoleFilter(e.target.value); setPage(1) }}
          >
            <option value="">全部角色</option>
            {roles.map(r => <option key={r.id} value={r.name}>{ROLE_LABELS[r.name] || r.name}</option>)}
          </select>
          <select
            className="select-field w-full py-2 text-sm"
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
          >
            <option value="">全部状态</option>
            <option value="active">启用</option>
            <option value="inactive">禁用</option>
          </select>
        </div>
      </div>

      {/* 表格 */}
      <div className="card overflow-hidden">
        <div className="border-b border-cloud-300/60 bg-cloud-100/30 px-4 py-3">
          <h3 className="text-sm font-semibold text-ink-body">用户列表</h3>
          <p className="mt-1 text-xs text-ink-muted">{ROLE_DETAILS_COPY.helper}</p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-cloud-300/60 text-left">
                <th className="px-3 py-2.5 text-xs font-medium text-ink-muted">ID</th>
                <th className="px-3 py-2.5 text-xs font-medium text-ink-muted">用户名</th>
                <th className="px-3 py-2.5 text-xs font-medium text-ink-muted">邮箱</th>
                <th className="px-3 py-2.5 text-xs font-medium text-ink-muted">角色</th>
                <th className="px-3 py-2.5 text-xs font-medium text-ink-muted">状态</th>
                <th className="px-3 py-2.5 text-xs font-medium text-ink-muted">最后登录</th>
                <th className="px-3 py-2.5 text-xs font-medium text-ink-muted">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => {
                const role = resolveRoleDetails(u.role_name)
                const roleLabel = ROLE_LABELS[u.role_name] || u.role_name || '只读'
                const permissionCount = role.permissions?.length || 0
                const isRolePopoverOpen = rolePopover?.sourceId === u.id

                return (
                  <tr key={u.id} className="border-b border-cloud-200 transition-colors hover:bg-cloud-200/50">
                    <td className="px-3 py-2 font-mono text-xs text-ink-muted">{u.id}</td>
                    <td className="flex items-center gap-1.5 px-3 py-2 font-medium text-ink-body">
                      {u.role_name === 'super_admin' ? <Shield size={12} className="text-rose-500" />
                        : u.role_name === 'dept_admin' ? <Shield size={12} className="text-amber-500" />
                        : u.role_name === 'teacher' ? <Edit3 size={12} className="text-sky-500" />
                        : <User size={12} className="text-ink-muted" />}
                      {u.username}
                      {u.id === me?.id && <span className="ml-1 text-2xs text-sky-500">(我)</span>}
                    </td>
                    <td className="px-3 py-2 text-xs text-ink-muted">{u.email}</td>
                    <td className="relative overflow-visible px-3 py-2">
                      <div className="relative inline-flex overflow-visible">
                        <button
                          type="button"
                          onClick={(event) => openRoleDetails(u.role_name, u.id, event.currentTarget)}
                          onMouseEnter={(event) => previewRoleDetails(u.role_name, u.id, event.currentTarget)}
                          onMouseLeave={scheduleHoverClose}
                          onFocus={(event) => previewRoleDetails(u.role_name, u.id, event.currentTarget)}
                          onBlur={scheduleHoverClose}
                          className="group -ml-1.5 inline-flex items-center gap-2 rounded-xl px-1.5 py-1 transition-colors hover:bg-cloud-100/80 focus-visible:bg-cloud-100"
                          title={permissionCount > 0 ? `点击查看 ${permissionCount} 项权限` : '点击查看角色权限详情'}
                          aria-label={`查看${roleLabel}权限详情`}
                          aria-controls="role-permission-panel"
                          aria-expanded={isRolePopoverOpen}
                          aria-haspopup="dialog"
                        >
                          <span
                            data-role-chip="true"
                            className={`rounded-lg border px-1.5 py-0.5 text-2xs ${ROLE_COLORS[u.role_name] || ROLE_COLORS.student}`}
                          >
                            {roleLabel}
                          </span>
                          <span className="whitespace-nowrap text-2xs text-ink-muted transition-colors group-hover:text-sky-600">
                            {role.detailsAvailable ? `${permissionCount} 项权限` : '查看权限'}
                          </span>
                        </button>

                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`rounded-lg px-1.5 py-0.5 text-2xs ${u.is_active ? 'border border-sage-200 bg-sage-50 text-sage-600' : 'border border-rose-200 bg-rose-50 text-rose-600'}`}>
                        {u.is_active ? '启用' : '禁用'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-ink-muted">
                      {u.last_login_at ? u.last_login_at.replace('T', ' ').substring(0, 16) : '从未登录'}
                    </td>
                    <td className="flex gap-1 px-3 py-2">
                      <button className="text-ink-muted transition-colors hover:text-amber-500" onClick={() => setEditUser(u)} title="编辑" aria-label={`编辑用户 ${u.username}`}>
                        <Edit3 size={13} aria-hidden="true" />
                      </button>
                      {u.id !== me?.id && (
                        <button className="text-ink-muted transition-colors hover:text-rose-500" onClick={() => handleDelete(u.id)} disabled={deletingId === u.id} title="删除" aria-label={`删除用户 ${u.username}`}>
                          {deletingId === u.id ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Trash2 size={13} aria-hidden="true" />}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
              {users.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-sm text-ink-muted">暂无用户</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="px-3 pb-2">
          <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
        </div>
      </div>

      {/* 弹窗 */}
      <CreateUserModal isOpen={showCreate} onClose={() => setShowCreate(false)} onCreated={loadUsers} roles={roles} />
      <EditUserModal user={editUser} roles={roles} isOpen={!!editUser} onClose={() => setEditUser(null)} onUpdated={loadUsers} />
      {activeRole && (
        <RolePermissionPopover
          role={activeRole}
          anchorRect={rolePopover?.anchorRect}
          pinned={!!rolePopover?.pinned}
          onClose={closeRoleDetails}
          onMouseEnter={clearHoverCloseTimer}
          onMouseLeave={scheduleHoverClose}
          popoverRef={popoverRef}
        />
      )}
    </div>
  )
}
