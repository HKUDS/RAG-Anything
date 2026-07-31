import test from 'node:test'
import assert from 'node:assert/strict'
import { deniedRouteRecovery, settingsRedirectDestination } from './settingsRouting.js'

test('legacy settings route sends readers to platform management', () => {
  assert.equal(settingsRedirectDestination(true), '/admin/platform')
})

test('legacy settings and denied direct routes have a stable personal fallback', () => {
  assert.equal(settingsRedirectDestination(false), deniedRouteRecovery)
  assert.equal(deniedRouteRecovery, '/preferences')
})
