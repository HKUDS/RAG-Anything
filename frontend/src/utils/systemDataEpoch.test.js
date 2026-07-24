import assert from 'node:assert/strict'
import test from 'node:test'
import {
  applySystemDataEpoch,
  synchronizeSystemDataEpoch,
  SYSTEM_DATA_EPOCH_KEY,
  startSystemDataEpochMonitor,
} from './systemDataEpoch.js'

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    get length() { return values.size },
    key(index) { return [...values.keys()][index] ?? null },
    getItem(key) { return values.has(key) ? values.get(key) : null },
    setItem(key, value) { values.set(key, String(value)) },
    removeItem(key) { values.delete(key) },
  }
}

test('a new data epoch removes application state but preserves unrelated origin data', () => {
  const local = memoryStorage({
    raganything_auth: 'token',
    raganything_theme: 'dark',
    autorepair_kb: 'old-kb',
    unrelated: 'keep',
  })
  const session = memoryStorage({
    'raganything:kb-list-cache': '["old"]',
    unrelated_session: 'keep',
  })

  assert.equal(applySystemDataEpoch('epoch-2', local, session), true)
  assert.equal(local.getItem('raganything_auth'), null)
  assert.equal(local.getItem('raganything_theme'), null)
  assert.equal(local.getItem('autorepair_kb'), null)
  assert.equal(session.getItem('raganything:kb-list-cache'), null)
  assert.equal(local.getItem('unrelated'), 'keep')
  assert.equal(session.getItem('unrelated_session'), 'keep')
  assert.equal(local.getItem(SYSTEM_DATA_EPOCH_KEY), 'epoch-2')
})

test('the same epoch is idempotent', () => {
  const local = memoryStorage({
    [SYSTEM_DATA_EPOCH_KEY]: 'epoch-2',
    raganything_auth: 'current-token',
  })
  const session = memoryStorage()

  assert.equal(applySystemDataEpoch('epoch-2', local, session), false)
  assert.equal(local.getItem('raganything_auth'), 'current-token')
})

test('bootstrap reads the public health epoch before rendering', async () => {
  const local = memoryStorage({ raganything_auth: 'old-token' })
  const session = memoryStorage()
  const fetchImpl = async (url, options) => {
    assert.equal(url, '/api/health')
    assert.equal(options.cache, 'no-store')
    return { ok: true, json: async () => ({ system_data_epoch: 'fresh' }) }
  }

  assert.equal(await synchronizeSystemDataEpoch({ fetchImpl, local, session }), true)
  assert.equal(local.getItem('raganything_auth'), null)
  assert.equal(local.getItem(SYSTEM_DATA_EPOCH_KEY), 'fresh')
})

test('an epoch change in another tab reloads the current tab', () => {
  const target = new EventTarget()
  let resets = 0
  const stop = startSystemDataEpochMonitor({
    intervalMs: 0,
    target,
    documentTarget: null,
    onReset: () => { resets += 1 },
  })
  const event = new Event('storage')
  Object.defineProperties(event, {
    key: { value: SYSTEM_DATA_EPOCH_KEY },
    oldValue: { value: 'old' },
    newValue: { value: 'new' },
  })

  target.dispatchEvent(event)
  stop()

  assert.equal(resets, 1)
})
