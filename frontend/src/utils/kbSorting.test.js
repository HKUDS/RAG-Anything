import assert from 'node:assert/strict'
import test from 'node:test'
import { getKnowledgeBaseUpdateTimestamp, sortKnowledgeBases } from './kbSorting.js'

const knowledgeBases = [
  {
    name: 'alpha',
    created: '2026-07-01T00:00:00Z',
    last_content_updated_at: '2026-07-08T00:00:00Z',
    stats: { documents: 2, entities: 18 },
  },
  {
    name: 'bravo',
    created: '2026-07-02T00:00:00Z',
    last_content_updated_at: '2026-07-10T00:00:00Z',
    stats: { documents: 7, entities: 9 },
  },
  {
    name: 'charlie',
    created: '2026-07-03T00:00:00Z',
    stats: { documents: 2, entities: 18 },
  },
]

test('sorts document counts in both directions and breaks ties by KB name', () => {
  assert.deepEqual(
    sortKnowledgeBases(knowledgeBases, {}, 'documents', 'asc').map(kb => kb.name),
    ['alpha', 'charlie', 'bravo']
  )
  assert.deepEqual(
    sortKnowledgeBases(knowledgeBases, {}, 'documents', 'desc').map(kb => kb.name),
    ['bravo', 'alpha', 'charlie']
  )
})

test('prefers refreshed entity statistics and leaves unavailable values last', () => {
  const stats = {
    bravo: { entities: 30, documents: 7 },
    charlie: { unavailable: true },
  }

  assert.deepEqual(
    sortKnowledgeBases(knowledgeBases, stats, 'entities', 'desc').map(kb => kb.name),
    ['bravo', 'alpha', 'charlie']
  )
})

test('sorts by content update time with creation time fallback and unknown values last', () => {
  const withUnknownTime = [...knowledgeBases, { name: 'delta', stats: { documents: 1, entities: 1 } }]

  assert.deepEqual(
    sortKnowledgeBases(withUnknownTime, {}, 'updated', 'desc').map(kb => kb.name),
    ['bravo', 'alpha', 'charlie', 'delta']
  )
  assert.deepEqual(
    sortKnowledgeBases(withUnknownTime, {}, 'updated', 'asc').map(kb => kb.name),
    ['charlie', 'alpha', 'bravo', 'delta']
  )
})

test('prefers the canonical update timestamp before legacy and creation fallbacks', () => {
  assert.equal(getKnowledgeBaseUpdateTimestamp({
    last_updated_at: '2026-08-05T08:00:00Z',
    last_content_updated_at: '2026-08-01T08:00:00Z',
    created: '2026-07-01T08:00:00Z',
  }), '2026-08-05T08:00:00Z')
  assert.equal(getKnowledgeBaseUpdateTimestamp({
    last_content_updated_at: '2026-08-01T08:00:00Z',
    created: '2026-07-01T08:00:00Z',
  }), '2026-08-01T08:00:00Z')
  assert.equal(getKnowledgeBaseUpdateTimestamp({ created: '2026-07-01T08:00:00Z' }), '2026-07-01T08:00:00Z')
})
