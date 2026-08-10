import test from 'node:test'
import assert from 'node:assert/strict'

import {
  readStoredAuth,
  writeStoredAuth,
  refreshStoredSession,
  resetRefreshStateForTests,
} from './authSession.js'

function installStorage(initial = null) {
  const values = new Map(initial ? [['raganything_auth', JSON.stringify(initial)]] : [])
  globalThis.localStorage = {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  }
  return values
}

test('refreshStoredSession single-flights concurrent refresh calls', async () => {
  installStorage({ token: 'old', refreshToken: 'refresh-old', user: { id: 1 } })
  resetRefreshStateForTests()
  let calls = 0
  const fetchImpl = async () => {
    calls += 1
    await new Promise(resolve => setTimeout(resolve, 0))
    return {
      status: 200,
      ok: true,
      json: async () => ({
        access_token: 'new', refresh_token: 'refresh-new',
        user: { id: 1, role: { name: 'student', permissions: [] } },
      }),
    }
  }

  const [first, second] = await Promise.all([
    refreshStoredSession(fetchImpl),
    refreshStoredSession(fetchImpl),
  ])
  assert.equal(calls, 1)
  assert.equal(first.access_token, 'new')
  assert.deepEqual(second, first)
  assert.equal(readStoredAuth().refreshToken, 'refresh-new')
})

test('refreshStoredSession keeps persistent credentials on transient failure', async () => {
  installStorage({ token: 'old', refreshToken: 'refresh-old', user: { id: 1 } })
  resetRefreshStateForTests()
  await assert.rejects(
    refreshStoredSession(async () => ({
      status: 503,
      ok: false,
      json: async () => ({ detail: 'temporarily unavailable' }),
    })),
    error => error.status === 503,
  )
  assert.equal(readStoredAuth().refreshToken, 'refresh-old')
})

test('refreshStoredSession reports authoritative refresh rejection without clearing storage', async () => {
  installStorage({ token: 'old', refreshToken: 'refresh-old', user: { id: 1 } })
  resetRefreshStateForTests()
  const result = await refreshStoredSession(async () => ({ status: 401, ok: false }))
  assert.equal(result, null)
  assert.equal(readStoredAuth().refreshToken, 'refresh-old')
})

test('writeStoredAuth persists the complete user projection', () => {
  installStorage()
  writeStoredAuth({
    access_token: 'a', refresh_token: 'r',
    user: { id: 2, role: { name: 'teacher', permissions: ['kb:read'] } },
  })
  assert.equal(readStoredAuth().user.role.name, 'teacher')
})
