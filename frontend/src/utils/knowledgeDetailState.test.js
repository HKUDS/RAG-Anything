import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createLatestRequestGate,
  createKnowledgeDetailState,
  getDocumentListMode,
  markKnowledgeDetailRefreshing,
  mergeKnowledgeDetailSnapshot,
} from './knowledgeDetailState.js'

test('loading and errors are never represented as an empty knowledge base', () => {
  const loading = createKnowledgeDetailState('manuals')
  assert.equal(getDocumentListMode({ routeKB: 'manuals', state: loading, filteredCount: 0 }), 'loading')

  const failed = mergeKnowledgeDetailSnapshot(loading, 'manuals', {
    documents: { status: 'error', error: 'network unavailable' },
  })
  assert.equal(getDocumentListMode({ routeKB: 'manuals', state: failed, filteredCount: 0 }), 'error')
})

test('only a successful zero-document response is empty and filtering has a distinct mode', () => {
  const empty = createKnowledgeDetailState('manuals', {
    documents: { status: 'ready', data: [] },
    stats: { status: 'ready', data: { documents: 0 } },
  })
  assert.equal(getDocumentListMode({ routeKB: 'manuals', state: empty, filteredCount: 0 }), 'empty')

  const populated = createKnowledgeDetailState('manuals', {
    documents: { status: 'ready', data: [{ id: 'd1' }] },
  })
  assert.equal(getDocumentListMode({ routeKB: 'manuals', state: populated, filteredCount: 0, hasFilter: true }), 'no-match')
})

test('refresh failures retain ready data and expose a non-destructive refresh error', () => {
  const ready = createKnowledgeDetailState('manuals', {
    documents: { status: 'ready', data: [{ id: 'd1' }] },
    stats: { status: 'ready', data: { documents: 1 } },
  })
  const refreshing = markKnowledgeDetailRefreshing(ready)
  assert.equal(refreshing.documents.refreshing, true)

  const failedRefresh = mergeKnowledgeDetailSnapshot(refreshing, 'manuals', {
    documents: { status: 'error', error: 'refresh failed' },
    stats: { status: 'error', error: 'refresh failed' },
  })
  assert.deepEqual(failedRefresh.documents.data, [{ id: 'd1' }])
  assert.equal(failedRefresh.documents.status, 'ready')
  assert.equal(failedRefresh.documents.refreshError, 'refresh failed')
  assert.deepEqual(failedRefresh.stats.data, { documents: 1 })
})

test('authorization failures fail closed instead of retaining stale rows', () => {
  const ready = createKnowledgeDetailState('manuals', {
    documents: { status: 'ready', data: [{ id: 'secret' }] },
    stats: { status: 'ready', data: { documents: 1 } },
  })
  const denied = mergeKnowledgeDetailSnapshot(ready, 'manuals', {
    documents: { status: 'error', error: 'forbidden', failClosed: true },
    stats: { status: 'error', error: 'forbidden', failClosed: true },
  })
  assert.deepEqual(denied.documents.data, [])
  assert.equal(denied.documents.status, 'error')
  assert.deepEqual(denied.stats.data, {})
})

test('a state belonging to another KB is treated as loading', () => {
  const state = createKnowledgeDetailState('kb-a', {
    documents: { status: 'ready', data: [{ id: 'a' }] },
  })
  assert.equal(getDocumentListMode({ routeKB: 'kb-b', state, filteredCount: 1 }), 'loading')
})

test('only the latest navigation request remains eligible to navigate', () => {
  const gate = createLatestRequestGate()
  const first = gate.begin()
  const second = gate.begin()
  assert.equal(gate.isLatest(first), false)
  assert.equal(gate.isLatest(second), true)
  gate.invalidate()
  assert.equal(gate.isLatest(second), false)
})
