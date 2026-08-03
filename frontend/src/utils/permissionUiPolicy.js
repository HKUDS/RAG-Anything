// UI visibility policy only. Backend permission checks remain authoritative.
export const UI_PERMISSION_REQUIREMENTS = Object.freeze({
  kb: Object.freeze({ read: 'kb:read', write: 'kb:write', delete: 'kb:delete' }),
  agent: Object.freeze({ read: 'agent:read', write: 'agent:write', delete: 'agent:delete' }),
  graph: Object.freeze({ read: 'graph:read', write: 'graph:write', delete: 'graph:write' }),
  workflow: Object.freeze({ read: 'workflow:read', write: 'workflow:write', delete: 'workflow:write' }),
  autorepair: Object.freeze({ read: 'autorepair:read', write: 'autorepair:write', delete: 'autorepair:write' }),
  monitor: Object.freeze({ read: 'monitor:read', write: 'settings:write', delete: 'settings:write' }),
  settings: Object.freeze({ read: 'settings:read', write: 'settings:write', delete: 'settings:write' }),
})

export function createPermissionUiPolicy(hasPermission) {
  const can = permission => typeof hasPermission === 'function' && hasPermission(permission)
  return {
    canReadKnowledge: can(UI_PERMISSION_REQUIREMENTS.kb.read),
    canWriteKnowledge: can(UI_PERMISSION_REQUIREMENTS.kb.write),
    canDeleteKnowledge: can(UI_PERMISSION_REQUIREMENTS.kb.delete),
    canReadAgents: can(UI_PERMISSION_REQUIREMENTS.agent.read),
    canWriteAgents: can(UI_PERMISSION_REQUIREMENTS.agent.write),
    canDeleteAgents: can(UI_PERMISSION_REQUIREMENTS.agent.delete),
    canReadGraph: can(UI_PERMISSION_REQUIREMENTS.graph.read),
    canWriteGraph: can(UI_PERMISSION_REQUIREMENTS.graph.write),
    canReadWorkflow: can(UI_PERMISSION_REQUIREMENTS.workflow.read),
    canWriteWorkflow: can(UI_PERMISSION_REQUIREMENTS.workflow.write),
    canDeleteWorkflow: can(UI_PERMISSION_REQUIREMENTS.workflow.delete),
    canReadAutoRepair: can(UI_PERMISSION_REQUIREMENTS.autorepair.read),
    canWriteAutoRepair: can(UI_PERMISSION_REQUIREMENTS.autorepair.write),
    canDeleteAutoRepair: can(UI_PERMISSION_REQUIREMENTS.autorepair.delete),
    canReadMonitor: can(UI_PERMISSION_REQUIREMENTS.monitor.read),
    canMaintainMonitor: can(UI_PERMISSION_REQUIREMENTS.settings.write),
    canReadSettings: can(UI_PERMISSION_REQUIREMENTS.settings.read),
    canWriteSettings: can(UI_PERMISSION_REQUIREMENTS.settings.write),
  }
}

export const ROUTE_RECOVERY_CANDIDATES = Object.freeze([
  Object.freeze({ path: '/knowledge', permission: 'kb:read' }),
  Object.freeze({ path: '/agents', permission: 'agent:read' }),
  Object.freeze({ path: '/autorepair', permission: 'autorepair:read' }),
  Object.freeze({ path: '/workflow', permission: 'workflow:read' }),
  Object.freeze({ path: '/monitor', permission: 'monitor:read' }),
  Object.freeze({ path: '/admin/platform', permission: 'settings:read' }),
  Object.freeze({ path: '/admin/users', permission: 'users:read' }),
  Object.freeze({ path: '/admin/audit-logs', permission: 'audit:read' }),
  Object.freeze({ path: '/preferences', permission: null }),
])

export function getDeniedRouteRecovery(hasPermission, currentPath = '') {
  const can = permission => !permission || (typeof hasPermission === 'function' && hasPermission(permission))
  const current = String(currentPath || '')
  if (current.startsWith('/autorepair/agent') && can('autorepair:read')) return '/autorepair'
  return ROUTE_RECOVERY_CANDIDATES.find(candidate => candidate.path !== current && can(candidate.permission))?.path || '/preferences'
}

export function neutralObjectError(isForbidden, isMissing, fallback = '内容暂不可用，请稍后重试。') {
  if (isForbidden || isMissing) return '内容暂不可用，链接可能已失效。'
  return fallback
}
