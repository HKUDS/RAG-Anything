import test from 'node:test'
import assert from 'node:assert/strict'
import { deniedRouteRecovery, resolveDeniedRoute, settingsRedirectDestination } from './settingsRouting.js'

test('legacy settings route sends readers to platform management', () => {
  assert.equal(settingsRedirectDestination(true), '/admin/platform')
})

test('legacy settings and denied direct routes have a stable personal fallback', () => {
  assert.equal(settingsRedirectDestination(false), deniedRouteRecovery)
  assert.equal(deniedRouteRecovery, '/preferences')
})

test('denied routes recover to the first readable business page', () => {
  const permissions = new Set(['autorepair:read', 'workflow:read'])
  assert.equal(resolveDeniedRoute(value => permissions.has(value), '/admin/platform'), '/autorepair')
  assert.equal(resolveDeniedRoute(value => permissions.has(value), '/autorepair'), '/workflow')
})
