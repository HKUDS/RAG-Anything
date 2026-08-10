import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canEditKnowledgeBase,
  getKnowledgeBaseEditCapabilities,
  getKnowledgeBaseEditorTabs,
} from './knowledgeBaseEditor.js'

test('knowledge-base editor visibility consumes server capabilities only', () => {
  assert.deepEqual(getKnowledgeBaseEditCapabilities({ role_name: 'super_admin' }), {
    rename: false,
    manageMembers: false,
  })
  assert.equal(canEditKnowledgeBase({ capabilities: { rename: true } }), true)
  assert.equal(canEditKnowledgeBase({ capabilities: { manage_members: true } }), true)
  assert.equal(canEditKnowledgeBase({ capabilities: { rename: false, manage_members: false } }), false)
})

test('knowledge-base editor shows only authorized sections', () => {
  assert.deepEqual(getKnowledgeBaseEditorTabs({ capabilities: { rename: true } }), [
    { id: 'details', label: '基本信息' },
  ])
  assert.deepEqual(getKnowledgeBaseEditorTabs({ capabilities: { manage_members: true } }), [
    { id: 'members', label: '成员与权限' },
  ])
})
