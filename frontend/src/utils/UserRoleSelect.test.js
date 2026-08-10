import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ROLE_ORDER,
  canAssignRole,
  filterAssignableRoles,
  orderRoles,
} from './roleOrdering.js'

const roles = [
  { id: 5, name: 'student' },
  { id: 4, name: 'assistant' },
  { id: 3, name: 'teacher' },
  { id: 2, name: 'dept_admin' },
  { id: 1, name: 'super_admin' },
]

test('canAssignRole 允许同级分配', () => {
  for (const role of ROLE_ORDER) {
    assert.equal(canAssignRole(role, role), true, role + ' 应可分配同级')
  }
})

test('canAssignRole 允许向更低等级分配', () => {
  assert.equal(canAssignRole('super_admin', 'student'), true)
  assert.equal(canAssignRole('dept_admin', 'teacher'), true)
  assert.equal(canAssignRole('dept_admin', 'student'), true)
  assert.equal(canAssignRole('teacher', 'assistant'), true)
  assert.equal(canAssignRole('teacher', 'student'), true)
  assert.equal(canAssignRole('assistant', 'student'), true)
})

test('canAssignRole 拒绝向更高等级分配（升级不可）', () => {
  assert.equal(canAssignRole('dept_admin', 'super_admin'), false)
  assert.equal(canAssignRole('teacher', 'dept_admin'), false)
  assert.equal(canAssignRole('teacher', 'super_admin'), false)
  assert.equal(canAssignRole('assistant', 'teacher'), false)
  assert.equal(canAssignRole('student', 'assistant'), false)
  assert.equal(canAssignRole('student', 'super_admin'), false)
})

test('canAssignRole 对未知角色一律拒绝', () => {
  assert.equal(canAssignRole('unknown', 'student'), false)
  assert.equal(canAssignRole('super_admin', 'unknown'), false)
  assert.equal(canAssignRole(undefined, 'student'), false)
  assert.equal(canAssignRole('super_admin', undefined), false)
  assert.equal(canAssignRole(null, null), false)
})

test('orderRoles 按 ROLE_ORDER 降序排列角色', () => {
  assert.deepEqual(orderRoles(roles).map((role) => role.name), ROLE_ORDER)
})

test('filterAssignableRoles 按操作者等级过滤可选角色', () => {
  assert.deepEqual(filterAssignableRoles(roles, 'super_admin').map((role) => role.name), ROLE_ORDER)
  assert.deepEqual(
    filterAssignableRoles(roles, 'dept_admin').map((role) => role.name),
    ['dept_admin', 'teacher', 'assistant', 'student']
  )
  assert.deepEqual(filterAssignableRoles(roles, 'teacher').map((role) => role.name), ['teacher', 'assistant', 'student'])
  assert.deepEqual(filterAssignableRoles(roles, 'student').map((role) => role.name), ['student'])
  assert.deepEqual(filterAssignableRoles(roles, 'unknown'), [])
})

test('filterAssignableRoles 未提供操作者角色时拒绝分配', () => {
  assert.deepEqual(filterAssignableRoles(roles, undefined).map((role) => role.name), [])
  assert.deepEqual(filterAssignableRoles(roles, null).map((role) => role.name), [])
})

test('filterAssignableRoles 忽略未知目标角色', () => {
  const mixed = [...roles, { id: 99, name: 'legacy_admin' }]
  const names = filterAssignableRoles(mixed, 'super_admin').map((role) => role.name)
  assert.deepEqual(names, ROLE_ORDER)
  assert.ok(!names.includes('legacy_admin'))
})
