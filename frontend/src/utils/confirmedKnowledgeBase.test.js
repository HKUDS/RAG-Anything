import assert from 'node:assert/strict'
import test from 'node:test'

import { getKnowledgeBaseItems, isKnowledgeBaseConfirmed } from './confirmedKnowledgeBase.js'

test('knowledge base confirmation accepts only exact names from the current list', () => {
  const response = { knowledge_bases: [{ name: 'course-a' }, { name: 'course-b' }] }
  assert.equal(isKnowledgeBaseConfirmed(response, 'course-a'), true)
  assert.equal(isKnowledgeBaseConfirmed(response, 'course'), false)
  assert.equal(isKnowledgeBaseConfirmed(response, ''), false)
})

test('knowledge base confirmation fails closed for malformed or empty lists', () => {
  assert.deepEqual(getKnowledgeBaseItems(null), [])
  assert.deepEqual(getKnowledgeBaseItems({ knowledge_bases: null }), [])
  assert.equal(isKnowledgeBaseConfirmed({ knowledge_bases: [] }, 'course-a'), false)
})
