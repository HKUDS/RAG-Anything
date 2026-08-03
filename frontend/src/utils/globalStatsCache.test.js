import assert from 'node:assert/strict'
import test from 'node:test'

import { createGlobalStatsCache, GLOBAL_STATS_CACHE_TTL_MS } from './globalStatsCache.js'

test('reuses a cached value within the TTL without calling the loader again', async () => {
  let clock = 1_000
  const cache = createGlobalStatsCache({ now: () => clock })
  let calls = 0
  const loader = async () => ({ docs: ++calls })

  assert.deepEqual(await cache.getOrLoad('demo', loader), { docs: 1 })
  assert.deepEqual(await cache.getOrLoad('demo', loader), { docs: 1 })
  assert.equal(calls, 1)

  clock += GLOBAL_STATS_CACHE_TTL_MS - 1
  assert.deepEqual(await cache.getOrLoad('demo', loader), { docs: 1 })
  assert.equal(calls, 1)
})

test('treats an entry as expired once the TTL elapses', async () => {
  let clock = 1_000
  const cache = createGlobalStatsCache({ now: () => clock })
  let calls = 0
  const loader = async () => ({ docs: ++calls })

  assert.deepEqual(await cache.getOrLoad('demo', loader), { docs: 1 })
  clock += GLOBAL_STATS_CACHE_TTL_MS
  assert.deepEqual(await cache.getOrLoad('demo', loader), { docs: 2 })
  assert.equal(calls, 2)
})

test('keeps values isolated per key', async () => {
  const cache = createGlobalStatsCache()
  await cache.getOrLoad('kb-a', async () => ({ kb: 'a' }))
  await cache.getOrLoad('kb-b', async () => ({ kb: 'b' }))

  assert.equal(cache.get('kb-a').kb, 'a')
  assert.equal(cache.get('kb-b').kb, 'b')
  assert.equal(await cache.getOrLoad('kb-a', async () => ({ kb: 'x' })).then(v => v.kb), 'a')
})

test('deduplicates concurrent loads for the same key', async () => {
  let calls = 0
  let resolveLoader
  const cache = createGlobalStatsCache()
  const loader = () => {
    calls += 1
    return new Promise(resolve => { resolveLoader = resolve })
  }

  const first = cache.getOrLoad('demo', loader)
  const second = cache.getOrLoad('demo', loader)
  assert.strictEqual(first, second)
  await Promise.resolve()
  assert.equal(calls, 1)

  resolveLoader({ docs: 42 })
  assert.deepEqual(await first, { docs: 42 })
  assert.deepEqual(await second, { docs: 42 })
  assert.equal(calls, 1)
})

test('does not cache rejected loads so the next call retries', async () => {
  let calls = 0
  const cache = createGlobalStatsCache()
  const loader = async () => {
    calls += 1
    if (calls === 1) throw new Error('boom')
    return { docs: calls }
  }

  await assert.rejects(cache.getOrLoad('demo', loader), /boom/)
  assert.deepEqual(await cache.getOrLoad('demo', loader), { docs: 2 })
  assert.equal(calls, 2)
})

test('invalidate clears values and blocks stale in-flight commits', async () => {
  let clock = 1_000
  const cache = createGlobalStatsCache({ now: () => clock })
  let calls = 0
  let resolveFirst
  const loader = () => {
    calls += 1
    return new Promise(resolve => {
      if (calls === 1) resolveFirst = resolve
      else resolve({ docs: calls })
    })
  }

  const stale = cache.getOrLoad('demo', loader)
  await Promise.resolve()
  cache.invalidate()
  resolveFirst({ docs: 1 })

  assert.deepEqual(await stale, { docs: 1 })
  assert.equal(cache.get('demo'), undefined)

  assert.deepEqual(await cache.getOrLoad('demo', loader), { docs: 2 })
  assert.equal(calls, 2)
  assert.equal(cache.get('demo').docs, 2)
})

test('invalidate with a specific key evicts only that key', async () => {
  const cache = createGlobalStatsCache()
  await cache.getOrLoad('kb-a', async () => ({ kb: 'a' }))
  await cache.getOrLoad('kb-b', async () => ({ kb: 'b' }))

  cache.invalidate('kb-a')
  assert.equal(cache.get('kb-a'), undefined)
  assert.equal(cache.get('kb-b').kb, 'b')
})

test('set stores a value that getOrLoad reuses within the TTL', async () => {
  let clock = 1_000
  const cache = createGlobalStatsCache({ now: () => clock })
  cache.set('demo', { docs: 7 })
  assert.deepEqual(await cache.getOrLoad('demo', async () => ({ docs: 99 })), { docs: 7 })
})