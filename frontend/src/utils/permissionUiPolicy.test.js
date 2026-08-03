import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createPermissionUiPolicy,
  getDeniedRouteRecovery,
  neutralObjectError,
  ROUTE_RECOVERY_CANDIDATES,
} from './permissionUiPolicy.js'

const permissions = values => value => values.includes(value)

test('capability policy follows permissions rather than role names', () => {
  const student = createPermissionUiPolicy(permissions(['kb:read', 'agent:read', 'autorepair:read', 'graph:read']))
  assert.equal(student.canReadKnowledge, true)
  assert.equal(student.canWriteKnowledge, false)
  assert.equal(student.canReadAgents, true)
  assert.equal(student.canWriteAgents, false)
  assert.equal(student.canWriteAutoRepair, false)

  const teacher = createPermissionUiPolicy(permissions(['kb:read', 'kb:write', 'agent:read', 'agent:write']))
  assert.equal(teacher.canWriteAgents, true)
  assert.equal(teacher.canDeleteAgents, false)
})

test('five built-in role permission sets expose only their actual UI capabilities', () => {
  const roles = {
    student: ['kb:read', 'agent:read', 'autorepair:read', 'graph:read'],
    assistant: ['kb:read', 'kb:write', 'agent:read', 'monitor:read', 'autorepair:read', 'graph:read', 'graph:write'],
    teacher: ['kb:read', 'kb:write', 'agent:read', 'agent:write', 'monitor:read', 'workflow:read', 'autorepair:read', 'autorepair:write', 'graph:read', 'graph:write'],
    dept_admin: ['kb:read', 'kb:write', 'kb:delete', 'agent:read', 'agent:write', 'agent:delete', 'settings:read', 'monitor:read', 'workflow:read', 'workflow:write', 'autorepair:read', 'autorepair:write', 'graph:read', 'graph:write'],
    super_admin: ['kb:read', 'kb:write', 'kb:delete', 'agent:read', 'agent:write', 'agent:delete', 'settings:read', 'settings:write', 'monitor:read', 'workflow:read', 'workflow:write', 'autorepair:read', 'autorepair:write', 'graph:read', 'graph:write'],
  }

  const student = createPermissionUiPolicy(permissions(roles.student))
  assert.equal(student.canWriteKnowledge, false)
  assert.equal(student.canWriteAgents, false)
  assert.equal(student.canWriteAutoRepair, false)

  const assistant = createPermissionUiPolicy(permissions(roles.assistant))
  assert.equal(assistant.canWriteKnowledge, true)
  assert.equal(assistant.canWriteGraph, true)
  assert.equal(assistant.canWriteAgents, false)

  const teacher = createPermissionUiPolicy(permissions(roles.teacher))
  assert.equal(teacher.canWriteAgents, true)
  assert.equal(teacher.canDeleteAgents, false)
  assert.equal(teacher.canWriteWorkflow, false)

  const deptAdmin = createPermissionUiPolicy(permissions(roles.dept_admin))
  assert.equal(deptAdmin.canWriteWorkflow, true)
  assert.equal(deptAdmin.canWriteSettings, false)

  const superAdmin = createPermissionUiPolicy(permissions(roles.super_admin))
  assert.equal(superAdmin.canDeleteKnowledge, true)
  assert.equal(superAdmin.canMaintainMonitor, true)
  assert.equal(superAdmin.canWriteSettings, true)
})

test('denied route recovery prefers the first permitted destination and skips current path', () => {
  const has = permissions(['workflow:read', 'monitor:read'])
  assert.equal(getDeniedRouteRecovery(has, '/workflow'), '/monitor')
  assert.equal(getDeniedRouteRecovery(has, '/admin/platform'), '/workflow')
  assert.equal(getDeniedRouteRecovery(permissions([]), '/knowledge'), '/preferences')
  assert.deepEqual(ROUTE_RECOVERY_CANDIDATES.at(-1), { path: '/preferences', permission: null })
})

test('denied AutoRepair agent routes return to the readable AutoRepair dashboard', () => {
  const has = permissions(['kb:read', 'autorepair:read'])
  assert.equal(getDeniedRouteRecovery(has, '/autorepair/agent'), '/autorepair')
})

test('object-level forbidden and missing errors stay neutral', () => {
  assert.equal(neutralObjectError(true, false), '内容暂不可用，链接可能已失效。')
  assert.equal(neutralObjectError(false, true), '内容暂不可用，链接可能已失效。')
  assert.equal(neutralObjectError(false, false, '网络连接异常。'), '网络连接异常。')
})
