import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createKnowledgeDetailCache,
  knowledgeDetailCacheKey,
} from './knowledgeDetailCache.js'

test('keys values by authentication generation and KB name', () => {
  assert.notEqual(knowledgeDetailCacheKey('user-a', 'manuals'), knowledgeDetailCacheKey('user-b', 'manuals'))
  assert.notEqual(knowledgeDetailCacheKey('user-a', 'manuals'), knowledgeDetailCacheKey('user-a', 'training'))
  assert.throws(() => knowledgeDetailCacheKey('user-a', ''), /non-empty KB name/)
})

test('shares in-flight work and caches only within the current authentication generation', async () => {
  const cache = createKnowledgeDetailCache({ authGeneration: 'session-a' })
  let calls = 0
  let resolveLoader
  const loader = context => {
    calls += 1
    assert.deepEqual(context, { kbName: 'manuals', authGeneration: 'session-a' })
    return new Promise(resolve => { resolveLoader = resolve })
  }

  const first = cache.load('manuals', loader)
  const second = cache.load('manuals', loader)
  assert.strictEqual(first, second)
  await Promise.resolve()
  assert.equal(calls, 1)

  resolveLoader({ documents: ['d1'] })
  assert.deepEqual(await first, { documents: ['d1'] })
  assert.equal(calls, 1)
  assert.deepEqual(cache.read('manuals')?.value, { documents: ['d1'] })

  assert.equal(cache.setAuthGeneration('session-b'), true)
  assert.equal(cache.read('manuals'), null)
  assert.equal(cache.setAuthGeneration('session-b'), false)
})

test('returns fresh entries until the thirty-second TTL expires and retains stale data for refresh UI', async () => {
  let clock = 1_000
  const cache = createKnowledgeDetailCache({ now: () => clock })
  let calls = 0
  const loader = () => ({ documents: ++calls })

  assert.deepEqual(await cache.load('manuals', loader), { documents: 1 })
  clock += 30_000
  assert.equal(cache.read('manuals')?.fresh, true)
  assert.deepEqual(await cache.load('manuals', loader), { documents: 1 })
  assert.equal(calls, 1)

  clock += 1
  const stale = cache.read('manuals')
  assert.equal(stale?.fresh, false)
  assert.equal(stale?.ageMs, 30_001)
  assert.deepEqual(await cache.load('manuals', loader), { documents: 2 })
  assert.equal(calls, 2)
})

test('evicts least-recently-used resolved entries at the configured capacity', async () => {
  const cache = createKnowledgeDetailCache({ maxEntries: 2 })
  await cache.load('one', () => 'one')
  await cache.load('two', () => 'two')
  cache.read('one')
  await cache.load('three', () => 'three')

  assert.equal(cache.size, 2)
  assert.equal(cache.read('one')?.value, 'one')
  assert.equal(cache.read('two'), null)
  assert.equal(cache.read('three')?.value, 'three')
})

test('targeted and full invalidation prevent old in-flight reads from repopulating the cache', async () => {
  const cache = createKnowledgeDetailCache()
  let resolveTargeted
  const targeted = cache.load('manuals', () => new Promise(resolve => { resolveTargeted = resolve }))
  await Promise.resolve()
  cache.invalidate('manuals')
  resolveTargeted('old-targeted')
  await targeted
  assert.equal(cache.read('manuals'), null)

  let resolveAll
  const full = cache.load('training', () => new Promise(resolve => { resolveAll = resolve }))
  await Promise.resolve()
  cache.invalidateAll()
  resolveAll('old-full')
  await full
  assert.equal(cache.read('training'), null)
})
