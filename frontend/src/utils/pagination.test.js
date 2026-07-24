import assert from 'node:assert/strict'
import test from 'node:test'
import {
  DEFAULT_PAGE_SIZE,
  PAGE_SIZE_OPTIONS,
  clampPage,
  getStoredPageSize,
  getTotalPages,
  normalizePageSize,
  storePageSize,
} from './pagination.js'

test('pagination exposes the supported page sizes and defaults to ten', () => {
  assert.deepEqual(PAGE_SIZE_OPTIONS, [10, 20, 50])
  assert.equal(DEFAULT_PAGE_SIZE, 10)
  assert.equal(normalizePageSize('20'), 20)
  assert.equal(normalizePageSize('invalid'), 10)
  assert.equal(normalizePageSize('20.5'), 10)
  assert.equal(normalizePageSize('20 items'), 10)
  assert.equal(normalizePageSize(25, [25, 50], 50), 25)
})

test('pagination calculates at least one page for empty collections', () => {
  assert.equal(getTotalPages(0, 10), 1)
  assert.equal(getTotalPages(1, 10), 1)
  assert.equal(getTotalPages(21, 10), 3)
  assert.equal(getTotalPages(100, 50), 2)
  assert.equal(clampPage(3, getTotalPages(21, 20)), 2)
})

test('pagination clamps invalid and out of range pages', () => {
  assert.equal(clampPage(0, 4), 1)
  assert.equal(clampPage('3', 4), 3)
  assert.equal(clampPage('3 pages', 4), 1)
  assert.equal(clampPage(8, 4), 4)
  assert.equal(clampPage('invalid', 0), 1)
})

test('pagination persists valid page sizes and ignores invalid storage values', () => {
  const previousWindow = globalThis.window
  const values = new Map([['page-size', '20.5']])
  globalThis.window = {
    localStorage: {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    },
  }

  try {
    assert.equal(getStoredPageSize('page-size'), 10)
    assert.equal(storePageSize('page-size', 50), 50)
    assert.equal(getStoredPageSize('page-size'), 50)
    assert.equal(storePageSize('page-size', 'not-supported'), 10)
    assert.equal(values.get('page-size'), '10')
  } finally {
    if (previousWindow === undefined) delete globalThis.window
    else globalThis.window = previousWindow
  }
})
